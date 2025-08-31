"""
Job management system for persistent Discord bot interactions.
"""

import json
import os
import uuid
import logging
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime
import shutil

logger = logging.getLogger(__name__)

@dataclass
class Job:
    """Represents a persistent job with all metadata."""
    job_id: str
    message_id: int
    channel_id: int
    guild_id: Optional[int]
    original_text: str
    input_image_paths: List[str]  # Paths to saved input images
    output_image_paths: List[str]  # Paths to saved output images
    stitched_image_path: Optional[str]  # Path to stitched input image if applicable
    created_at: str
    updated_at: str
    status: str  # "waiting", "processing", "completed", "error"
    current_view_type: str  # "ProcessRequestView" or "StyleOptionsView"
    current_output_index: int  # For StyleOptionsView navigation

class JobManager:
    """Manages job persistence and loading."""
    
    def __init__(self, jobs_file: str = "jobs.json", jobs_dir: str = "jobs"):
        self.jobs_file = jobs_file
        self.jobs_dir = jobs_dir
        self.jobs: Dict[str, Job] = {}
        
        # Ensure directories exist
        os.makedirs(jobs_dir, exist_ok=True)
        
        # Load existing jobs
        self._load_jobs()
    
    def _load_jobs(self):
        """Load jobs from JSON file."""
        if os.path.exists(self.jobs_file):
            try:
                with open(self.jobs_file, 'r') as f:
                    jobs_data = json.load(f)
                
                for job_id, job_data in jobs_data.items():
                    self.jobs[job_id] = Job(**job_data)
                
                logger.info(f"Loaded {len(self.jobs)} existing jobs")
            except Exception as e:
                logger.error(f"Error loading jobs: {e}")
    
    def _save_jobs(self):
        """Save jobs to JSON file with atomic write."""
        try:
            # Create temporary file first
            temp_file = f"{self.jobs_file}.tmp"
            
            jobs_data = {}
            for job_id, job in self.jobs.items():
                jobs_data[job_id] = asdict(job)
            
            with open(temp_file, 'w') as f:
                json.dump(jobs_data, f, indent=2)
            
            # Atomic rename
            os.rename(temp_file, self.jobs_file)
            
            logger.debug(f"Saved {len(self.jobs)} jobs to {self.jobs_file}")
        except Exception as e:
            logger.error(f"Error saving jobs: {e}")
            # Clean up temp file if it exists
            if os.path.exists(f"{self.jobs_file}.tmp"):
                os.remove(f"{self.jobs_file}.tmp")
    
    def create_job(self, message_id: int, channel_id: int, guild_id: Optional[int], 
                   original_text: str, input_images: List[Any]) -> str:
        """Create a new job and return its ID."""
        job_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        # Create job directory
        job_dir = os.path.join(self.jobs_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)
        
        # Save input images to job directory
        input_image_paths = []
        for i, image in enumerate(input_images):
            filename = f"input_{i}_{timestamp.replace(':', '_')}.png"
            filepath = os.path.join(job_dir, filename)
            image.save(filepath)
            input_image_paths.append(filepath)
        
        # Create job
        job = Job(
            job_id=job_id,
            message_id=message_id,
            channel_id=channel_id,
            guild_id=guild_id,
            original_text=original_text,
            input_image_paths=input_image_paths,
            output_image_paths=[],
            stitched_image_path=None,
            created_at=timestamp,
            updated_at=timestamp,
            status="waiting",
            current_view_type="ProcessRequestView",
            current_output_index=0
        )
        
        self.jobs[job_id] = job
        self._save_jobs()
        
        logger.info(f"Created job {job_id} for message {message_id}")
        return job_id
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        return self.jobs.get(job_id)
    
    def update_job(self, job_id: str, **kwargs):
        """Update job fields."""
        if job_id in self.jobs:
            job = self.jobs[job_id]
            
            # Update fields
            for key, value in kwargs.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            
            # Update timestamp
            job.updated_at = datetime.now().isoformat()
            
            self._save_jobs()
            logger.debug(f"Updated job {job_id}")
    
    def add_output_image(self, job_id: str, image: Any, filename: str) -> str:
        """Add an output image to a job and return the saved path."""
        if job_id not in self.jobs:
            return ""
        
        job_dir = os.path.join(self.jobs_dir, job_id)
        filepath = os.path.join(job_dir, filename)
        
        # Save image
        image.save(filepath)
        
        # Update job
        job = self.jobs[job_id]
        job.output_image_paths.append(filepath)
        job.updated_at = datetime.now().isoformat()
        
        self._save_jobs()
        
        logger.debug(f"Added output image to job {job_id}: {filename}")
        return filepath
    
    def set_stitched_image(self, job_id: str, image: Any, filename: str) -> str:
        """Set the stitched image for a job and return the saved path."""
        if job_id not in self.jobs:
            return ""
        
        job_dir = os.path.join(self.jobs_dir, job_id)
        filepath = os.path.join(job_dir, filename)
        
        # Save image
        image.save(filepath)
        
        # Update job
        job = self.jobs[job_id]
        job.stitched_image_path = filepath
        job.updated_at = datetime.now().isoformat()
        
        self._save_jobs()
        
        logger.debug(f"Set stitched image for job {job_id}: {filename}")
        return filepath
    
    def get_all_jobs(self) -> Dict[str, Job]:
        """Get all jobs."""
        return self.jobs.copy()
    
    def cleanup_job(self, job_id: str):
        """Clean up a job and its files."""
        if job_id in self.jobs:
            # Remove job directory
            job_dir = os.path.join(self.jobs_dir, job_id)
            if os.path.exists(job_dir):
                shutil.rmtree(job_dir)
            
            # Remove from memory
            del self.jobs[job_id]
            self._save_jobs()
            
            logger.info(f"Cleaned up job {job_id}")

# Global job manager instance
job_manager = JobManager()