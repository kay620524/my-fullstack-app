from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, String, Boolean, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from typing import Optional
from datetime import datetime  # 🌟 新增：导入 Python 的时间模块


# ==========================================
# 1. 数据库模型部分
# ==========================================
class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    deadline: Mapped[str] = mapped_column(String(50))
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str] = mapped_column(String(50), default="生活")


# engine = create_engine("sqlite:///my_tasks.db")
engine = create_engine("postgresql://neondb_owner:npg_UuP2F0YpxivD@ep-bitter-bird-ao4ytzpt.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require")
Base.metadata.create_all(engine)

app = FastAPI(title="我的终极任务管理器 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# 2. 互联网接口部分
# ==========================================
@app.get("/")
def read_root():
    return {"message": "全栈大结局 API 运行中！"}


@app.get("/tasks")
def get_all_tasks(category: Optional[str] = None):
    with Session(engine) as session:
        query = select(Task)
        if category and category != "全部":
            query = query.where(Task.category == category)

        tasks = session.scalars(query).all()

        # 🌟 核心逻辑：后端计算截止日期状态
        result = []
        today = datetime.now().date()  # 获取现实世界今天的日期

        for task in tasks:
            status = "normal"

            # 只有未完成的任务才需要判断是否逾期
            if not task.is_completed and task.deadline and "-" in task.deadline:
                try:
                    # 将字符串 "2026-07-06" 转换成真正的 Date 对象来比大小
                    task_date = datetime.strptime(task.deadline, "%Y-%m-%d").date()
                    if task_date < today:
                        status = "overdue"  # 逾期
                    elif task_date == today:
                        status = "today"  # 今天截止
                except ValueError:
                    pass  # 如果用户没填标准日期，就按正常处理

            # 手动拼装返回给前端的字典数据
            result.append({
                "id": task.id,
                "title": task.title,
                "deadline": task.deadline,
                "is_completed": task.is_completed,
                "category": task.category,
                "status": status  # 🌟 把算好的状态传给网页
            })
        return result


# 【增、改、删 接口保持不变】
class TaskCreate(BaseModel):
    title: str
    deadline: str
    category: str


@app.post("/tasks")
def create_task(task_in: TaskCreate):
    with Session(engine) as session:
        new_task = Task(title=task_in.title, deadline=task_in.deadline, category=task_in.category)
        session.add(new_task)
        session.commit()
        session.refresh(new_task)
        return new_task


@app.put("/tasks/{task_id}")
def toggle_task(task_id: int):
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task: raise HTTPException(status_code=404, detail="找不到")
        task.is_completed = not task.is_completed
        session.commit()
        return {"message": "状态更新成功！"}


@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task: raise HTTPException(status_code=404, detail="找不到")
        session.delete(task)
        session.commit()
        return {"message": "删除成功！"}