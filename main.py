from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pydantic import BaseModel
from typing import List
from passlib.context import CryptContext
import jwt
import datetime

# 1. 基础配置与安全密钥
SECRET_KEY = "MY_SUPER_SECRET_KEY_12345"  # 现实中这把钥匙要藏好
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# 2. 数据库连接（⚠️请把这里替换为你自己的 Neon 真实网址！）
DATABASE_URL = "postgresql://neondb_owner:npg_UuP2F0YpxivD@ep-bitter-bird-ao4ytzpt.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# 3. 数据库模型 (Models)
class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)


class TaskDB(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    deadline = Column(String, default="无期限")
    category = Column(String, default="生活")
    is_completed = Column(Boolean, default=False)
    # 建立血缘关系：通过外键与用户表绑定（允许为空是为了兼容你数据库里之前没有主人的旧数据）
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)


Base.metadata.create_all(bind=engine)


# 4. Pydantic 数据验证模型 (Schemas)
class UserCreate(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class TaskCreate(BaseModel):
    title: str
    deadline: str = "无期限"
    category: str = "生活"


class TaskResponse(BaseModel):
    id: int
    title: str
    deadline: str
    category: str
    is_completed: bool
    owner_id: int = None

    class Config:
        from_attributes = True


# 5. 核心辅助函数 (工具包)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 验证“数字手环”的保安函数
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="无效的令牌")
        user = db.query(UserDB).filter(UserDB.username == username).first()
        if user is None:
            raise HTTPException(status_code=401, detail="用户不存在")
        return user
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="凭证已过期或无效")


# 6. 初始化 FastAPI 实例与跨域配置
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ======= 7. 新增的认证接口 (Auth APIs) =======

@app.post("/register", status_code=21)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    # 检查用户名是否被抢注
    existing_user = db.query(UserDB).filter(UserDB.username == user_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="该用户名已被注册")
    # 密码哈希加密，绝不存明文！
    hashed_pwd = pwd_context.hash(user_data.password)
    new_user = UserDB(username=user_data.username, hashed_password=hashed_pwd)
    db.add(new_user)
    db.commit()
    return {"message": "注册成功！"}


@app.post("/login", response_model=Token)
def login(user_data: UserCreate, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == user_data.username).first()
    # 验证账号存在且密码匹配
    if not user or not pwd_context.verify(user_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="用户名或密码错误")

    # 登录成功，制作有有效期的“数字手环”(JWT Token)
    exp_time = datetime.datetime.utcnow() + datetime.timedelta(hours=24)  # 24小时有效
    token_payload = {"sub": user.username, "exp": exp_time}
    token = jwt.encode(token_payload, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}


# ======= 8. 升级后的任务接口 (Tasks APIs - 关联用户) =======

@app.get("/tasks", response_model=List[TaskResponse])
def get_tasks(db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    # 🔐 保安拦截后：只捞出当前登录用户的专属任务！
    return db.query(TaskDB).filter(TaskDB.owner_id == current_user.id).all()


@app.post("/tasks", response_model=TaskResponse)
def create_task(task: TaskCreate, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    # 🔐 新建任务时，自动盖上当前用户的“主人戳”
    new_task = TaskDB(
        title=task.title,
        deadline=task.deadline,
        category=task.category,
        owner_id=current_user.id
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    return new_task


@app.put("/tasks/{task_id}")
def toggle_task(task_id: int, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    # 🔐 只能修改属于自己的任务
    task = db.query(TaskDB).filter(TaskDB.id == task_id, TaskDB.owner_id == current_user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或无权操作")
    task.is_completed = not task.is_completed
    db.commit()
    return {"message": "状态更新成功"}


@app.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    # 🔐 只能删除属于自己的任务
    task = db.query(TaskDB).filter(TaskDB.id == task_id, TaskDB.owner_id == current_user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或无权操作")
    db.delete(task)
    db.commit()
    return {"message": "任务已彻底删除"}