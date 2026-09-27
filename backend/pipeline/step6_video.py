"""
Step 6: 视频生成 - 根据聚类结果生成最终视频切片
"""
import json
import logging
import os
import re
from typing import List, Dict, Any, Optional
from pathlib import Path

# 导入依赖
from ..utils.video_processor import VideoProcessor
from ..core.shared_config import METADATA_DIR, CLIPS_DIR, COLLECTIONS_DIR

logger = logging.getLogger(__name__)

class VideoGenerator:
    """视频生成器"""
    
    def __init__(self, clips_dir: Optional[str] = None, collections_dir: Optional[str] = None, metadata_dir: Optional[str] = None, progress_callback=None):
        # 强制使用项目内专属目录，不使用全局目录作为后备
        if not clips_dir:
            raise ValueError("clips_dir 参数是必需的，不能使用全局路径")
        if not collections_dir:
            raise ValueError("collections_dir 参数是必需的，不能使用全局路径")
        
        self.clips_dir = Path(clips_dir)
        self.collections_dir = Path(collections_dir)
        self.metadata_dir = Path(metadata_dir) if metadata_dir else METADATA_DIR
        self.progress_callback = progress_callback
        
        # 确保目录存在
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.collections_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建VideoProcessor实例，强制使用项目内路径
        self.video_processor = VideoProcessor(clips_dir=str(self.clips_dir), collections_dir=str(self.collections_dir))
    
    def generate_clips(self, clips_with_titles: List[Dict], input_video: Path) -> List[Path]:
        """
        生成切片视频
        
        Args:
            clips_with_titles: 带标题的片段数据
            input_video: 输入视频路径
            
        Returns:
            生成的切片视频路径列表
        """
        logger.info("开始生成切片视频...")
        
        # 准备切片数据
        clips_data = []
        for clip in clips_with_titles:
            clips_data.append({
                'id': clip['id'],
                'title': clip.get('generated_title', f"Clip {clip['id']}"),
                'start_time': clip['start_time'],
                'end_time': clip['end_time']
            })
        
        # 批量生成切片
        successful_clips = self.video_processor.batch_extract_clips(
            input_video, clips_data,
            progress_callback=self.progress_callback,
            progress_offset=0.0,
            progress_span=0.70,
        )
        
        logger.info(f"切片视频生成完成，共{len(successful_clips)}个切片")
        return successful_clips
    
    def generate_collections(self, collections_data: List[Dict]) -> List[Dict]:
        """
        生成合集视频
        
        Args:
            collections_data: 合集数据
            
        Returns:
            生成的合集信息列表，包含视频路径和缩略图路径
        """
        logger.info("开始生成合集视频...")
        
        # 生成合集视频和缩略图
        successful_collections = self.video_processor.create_collections_from_metadata(
            collections_data,
            progress_callback=self.progress_callback,
            progress_offset=0.70,
            progress_span=0.30,
        )
        
        logger.info(f"合集视频生成完成，共{len(successful_collections)}个合集")
        return successful_collections
    
    def save_clip_metadata(self, clips_with_titles: List[Dict], output_path: Optional[Path] = None) -> Path:
        """
        保存最终的切片元数据到clips_metadata.json
        
        Args:
            clips_with_titles: 带标题的片段数据（来自step4）
            output_path: 输出路径，默认为clips_metadata.json
            
        Returns:
            保存的文件路径
            
        Note:
            此方法保存的是最终的切片元数据，包含视频生成后的完整信息。
            与step4的step4_titles.json不同，这里保存的是用于前端展示的最终数据。
        """
        if output_path is None:
            output_path = self.metadata_dir / "clips_metadata.json"
        
        # 确保目录存在
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 保存数据
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(clips_with_titles, f, ensure_ascii=False, indent=2)
        
        logger.info(f"切片元数据已保存到: {output_path}")
        return output_path
    
    def save_collection_metadata(self, collections_data: List[Dict], output_path: Optional[Path] = None) -> Path:
        """
        保存合集元数据
        
        Args:
            collections_data: 合集数据
            output_path: 输出路径
            
        Returns:
            保存的文件路径
        """
        if output_path is None:
            output_path = self.metadata_dir / "collections_metadata.json"
        
        # 确保目录存在
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 保存数据
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(collections_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"合集元数据已保存到: {output_path}")
        return output_path

def run_step6_video(clips_with_titles_path: Path, collections_path: Path, 
                   input_video: Path, output_dir: Optional[Path] = None, 
                   clips_dir: Optional[str] = None, collections_dir: Optional[str] = None, 
                   metadata_dir: Optional[str] = None, progress_callback=None) -> Dict:
    """
    运行Step 6: 视频切割
    
    Args:
        clips_with_titles_path: 带标题的片段文件路径
        collections_path: 合集文件路径
        input_video: 输入视频路径
        output_dir: 输出目录
        
    Returns:
        生成结果信息
    """
    # 加载数据
    with open(clips_with_titles_path, 'r', encoding='utf-8') as f:
        clips_with_titles = json.load(f)
    
    with open(collections_path, 'r', encoding='utf-8') as f:
        collections_data = json.load(f)
    
    # 创建视频生成器
    generator = VideoGenerator(
        clips_dir=clips_dir, collections_dir=collections_dir,
        metadata_dir=metadata_dir, progress_callback=progress_callback,
    )
    
    # 生成切片视频
    successful_clips = generator.generate_clips(clips_with_titles, input_video)
    
    # 生成合集视频
    successful_collections = generator.generate_collections(collections_data)
    
    # 保存元数据到项目目录
    # 注意：clips_metadata.json在这里保存，包含最终的切片元数据（包含视频路径等信息）
    # 这与step4的step4_titles.json不同，step4只保存带标题的片段数据
    if metadata_dir:
        project_metadata_dir = Path(metadata_dir)
        generator.save_clip_metadata(clips_with_titles, project_metadata_dir / "clips_metadata.json")
        generator.save_collection_metadata(collections_data, project_metadata_dir / "collections_metadata.json")
    else:
        generator.save_clip_metadata(clips_with_titles)
        generator.save_collection_metadata(collections_data)
    
    # Automatically render the selected clips into upload-ready YouTube Shorts.
    # Keep the raw Step 6 clips intact under output/clips; final publishable files
    # are written by the existing Shorts exporter under output/exports.
    final_exports: List[Dict[str, Any]] = []
    skipped_short_exports: List[Dict[str, Any]] = []
    auto_publish = os.getenv("AUTOCLIP_AUTO_PUBLISH_SHORTS", "true").strip().lower() not in {"0", "false", "no", "off"}
    if auto_publish and successful_clips:
        from ..services.publish_export import ExportRequest, export_clip
        from .quality import short_publish_check, select_short_candidates

        # Content architecture: only publish candidates that survived the
        # complete-thought + structure quality gate. Raw Step 6 clips remain
        # available for human editing even when they are not publishable Shorts.
        requested_count = 0
        try:
            from ..core.llm_manager import get_llm_manager
            requested_count = int(get_llm_manager().get_processing_setting("processing_clip_count") or 0)
        except Exception:
            requested_count = 0
        candidate_clips = select_short_candidates(clips_with_titles, requested_count=requested_count)
        candidate_ids = {str(item.get("id")) for item in candidate_clips}

        successful_ids = []
        for clip in clips_with_titles:
            clip_id = str(clip.get("id"))
            if not any(path.name.startswith(f"{clip_id}_") for path in successful_clips):
                continue

            publishable = clip.get("short_publishable")
            reasons = clip.get("short_publish_rejection_reasons")
            if publishable is not True:
                # Re-check here so old/incomplete metadata cannot bypass the gate.
                publishable, reasons = short_publish_check(clip)
            if not publishable:
                skipped_short_exports.append({
                    "ok": False,
                    "clip_id": clip_id,
                    "skipped": True,
                    "reason": "short_quality_gate",
                    "reasons": reasons or ["quality_gate_failed"],
                })
                logger.info(
                    "自动 Shorts 跳过 clip_id=%s：质量门禁失败 (%s)",
                    clip_id,
                    ", ".join(reasons or ["quality_gate_failed"]),
                )
                continue

            if clip_id not in candidate_ids:
                skipped_short_exports.append({
                    "ok": False,
                    "clip_id": clip_id,
                    "skipped": True,
                    "reason": "not_selected_short_candidate",
                    "reasons": ["candidate_selection_limit"],
                })
                continue
            successful_ids.append(clip_id)

        project_id = Path(metadata_dir).parent.name if metadata_dir else generator.metadata_dir.parent.name
        total = len(successful_ids)
        for index, clip_id in enumerate(successful_ids, start=1):
            clip = next((item for item in clips_with_titles if str(item.get("id")) == clip_id), {})
            try:
                export_result = export_clip(
                    ExportRequest(
                        project_id=project_id,
                        clip_id=clip_id,
                        preset="shorts",
                        subtitles=True,
                        title_card=True,
                        hook_text=clip.get("short_hook"),
                    ),
                    progress_callback=(
                        (lambda percent, i=index, total=total: generator.progress_callback(
                            0.70 + (0.30 * ((i - 1) + percent / 100.0) / max(total, 1)),
                            f"Publishing Short {i}/{total}",
                        ))
                        if generator.progress_callback else None
                    ),
                )
                final_exports.append(export_result)
            except Exception as exc:  # noqa: BLE001
                logger.exception("自动 Shorts 导出失败: clip_id=%s", clip_id)
                final_exports.append({"ok": False, "clip_id": clip_id, "error": str(exc)[:500]})

    # 返回结果信息
    result = {
        'clips_generated': len(successful_clips),
        'collections_generated': len(successful_collections),
        'clip_paths': [str(path) for path in successful_clips],
        'collection_paths': [collection['video_path'] for collection in successful_collections],
        'collection_thumbnails': [collection['thumbnail_path'] for collection in successful_collections if collection['thumbnail_path']],
        'collections_info': successful_collections,  # 包含完整的合集信息
        'auto_publish_shorts': auto_publish,
        'final_exports': final_exports,
        'skipped_short_exports': skipped_short_exports,
        'final_exports_generated': sum(1 for item in final_exports if item.get('ok')),
        'final_exports_failed': sum(1 for item in final_exports if not item.get('ok')),
        'final_exports_skipped': len(skipped_short_exports),
    }
    
    logger.info(f"视频生成完成: {result['clips_generated']}个切片, {result['collections_generated']}个合集")
    
    # 保存结果到输出文件
    if output_dir is not None:
        output_path = output_dir / "step6_video_output.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"步骤6结果已保存到: {output_path}")
    
    return result