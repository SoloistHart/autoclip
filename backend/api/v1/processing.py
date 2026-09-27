"""
处理API路由
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...services.processing_service import ProcessingService
from ...services.project_service import ProjectService

router = APIRouter()


def get_processing_service(db: Session = Depends(get_db)) -> ProcessingService:
    """Dependency to get processing service."""
    return ProcessingService(db)


def get_project_service(db: Session = Depends(get_db)) -> ProjectService:
    """Dependency to get project service."""
    return ProjectService(db)


@router.post("/projects/{project_id}/process")
async def process_project(
    project_id: str,
    processing_service: ProcessingService = Depends(get_processing_service)
):
    """开始处理项目"""
    try:
        result = processing_service.process_project(project_id)
        return {
            "message": "项目处理已开始",
            "project_id": project_id,
            "result": result
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"缺少必要文件: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.get("/projects/{project_id}/processing-status")
async def get_processing_status(
    project_id: str,
    project_service: ProjectService = Depends(get_project_service),
    processing_service: ProcessingService = Depends(get_processing_service)
):
    """获取项目处理状态"""
    try:
        project = project_service.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        tasks = project.tasks if hasattr(project, "tasks") else []
        latest_task = None
        if tasks:
            latest_task = max(tasks, key=lambda task: task.created_at) if hasattr(tasks[0], "created_at") else tasks[0]

        if not latest_task:
            return {
                "status": "pending",
                "current_step": 0,
                "total_steps": 6,
                "step_name": "等待开始",
                "progress": 0,
                "error_message": None,
            }

        return processing_service.get_processing_status(project_id, str(latest_task.id))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")


@router.post("/projects/{project_id}/process/step/{step_number}")
async def process_step(
    project_id: str,
    step_number: int,
    processing_service: ProcessingService = Depends(get_processing_service)
):
    """处理单个步骤"""
    if step_number < 1 or step_number > 6:
        raise HTTPException(status_code=400, detail="步骤编号必须在1-6之间")
    
    try:
        # 这里可以扩展为处理单个步骤
        result = processing_service.process_project(project_id)
        return {
            "message": f"步骤 {step_number} 处理完成",
            "project_id": project_id,
            "step": step_number,
            "result": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"步骤处理失败: {str(e)}")