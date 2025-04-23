import requests
import os
from typing import Dict, List, Optional
import logging
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EmployeeSearchTool:
    """Tool for searching employees using PDL's Person Identify API"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize with API key"""
        self.api_key = api_key or os.getenv('PDL_API_KEY')
        if not self.api_key:
            raise ValueError("PDL_API_KEY environment variable is required")
        
        self.base_url = "https://api.peopledatalabs.com/v5/person/identify"
        self.headers = {
            "X-Api-Key": self.api_key
        }

    def search_employees(self, company_name: str) -> Dict:
        """
        Search for employees at a company and filter for engineering roles.
        
        Args:
            company_name: Name of the company to search
            
        Returns:
            Dict containing:
            - total_employees: Total number of employees found
            - engineering_employees: List of engineering employees
            - engineering_percentage: Percentage of engineering employees
        """
        try:
            # Define engineering-related job titles to search for
            engineering_titles = [
                "software engineer", "engineering manager", "cto", 
                "vp engineering", "director of engineering", "engineering lead",
                "senior software engineer", "principal engineer"
            ]
            
            # Prepare search parameters
            params = {
                "company": company_name,
                "job_title": engineering_titles,
                "pretty": True,
                "size": 100  # Maximum results per page
            }
            
            # Make API request
            response = requests.get(
                self.base_url,
                headers=self.headers,
                params=params
            )
            response.raise_for_status()
            data = response.json()
            
            if data["status"] != 200:
                raise Exception(f"API returned status {data['status']}")
            
            # Process results
            matches = data.get("matches", [])
            engineering_employees = []
            
            for match in matches:
                employee_data = match["data"]
                engineering_employees.append({
                    "name": employee_data.get("full_name"),
                    "title": employee_data.get("job_title"),
                    "location": employee_data.get("location", {}).get("country"),
                    "linkedin_url": employee_data.get("linkedin_url")
                })
            
            # Calculate engineering percentage
            # Note: This is an estimate since we don't have exact total
            total_employees = len(matches)  # This is an approximation
            engineering_percentage = (len(engineering_employees) / total_employees * 100) if total_employees > 0 else 0
            
            return {
                "total_employees": total_employees,
                "engineering_employees": engineering_employees,
                "engineering_percentage": round(engineering_percentage, 2)
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error processing employee data: {str(e)}")
            raise 