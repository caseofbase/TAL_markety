import requests
import os
from typing import Dict, Optional, List
import logging
from datetime import datetime, timedelta
import json
from pathlib import Path
from dotenv import load_dotenv
import traceback
import hashlib
import time
import openai
import re


# Set up logging with more detailed format
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PDLError(Exception):
    """Base exception for PDL API errors"""
    pass

class Cache:
    """Simple file-based cache system"""
    
    def __init__(self, cache_dir: str = ".cache", ttl_hours: int = 24):
        self.cache_dir = Path(cache_dir)
        self.ttl = timedelta(hours=ttl_hours)
        self.cache_dir.mkdir(exist_ok=True)
        
    def clear(self):
        """Clear all cached data"""
        try:
            count = 0
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()
                count += 1
            logger.info(f"Cleared {count} cache files")
        except Exception as e:
            logger.warning(f"Error clearing cache: {str(e)}")
        
    def _get_cache_key(self, params: dict) -> str:
        """Generate a unique cache key from search parameters"""
        # Sort the parameters to ensure consistent keys
        sorted_params = json.dumps(params, sort_keys=True)
        key = hashlib.md5(sorted_params.encode()).hexdigest()
        logger.debug(f"Generated cache key {key} for params: {sorted_params}")
        return key
        
    def _get_cache_path(self, key: str) -> Path:
        """Get the file path for a cache key"""
        return self.cache_dir / f"{key}.json"
        
    def get(self, params: dict) -> Optional[dict]:
        """Retrieve cached results if they exist and haven't expired"""
        try:
            key = self._get_cache_key(params)
            cache_path = self._get_cache_path(key)
            
            if not cache_path.exists():
                logger.debug(f"No cache file found for key {key}")
                return None
                
            with cache_path.open('r') as f:
                cached_data = json.load(f)
                
            # Check if cache has expired
            cached_time = datetime.fromtimestamp(cached_data['timestamp'])
            if datetime.now() - cached_time > self.ttl:
                logger.info(f"Cache expired for key {key}, removing file")
                cache_path.unlink()  # Remove expired cache
                return None
                
            logger.info(f"Found valid cache for key {key}")
            return cached_data['data']
            
        except Exception as e:
            logger.warning(f"Error reading cache: {str(e)}")
            return None
            
    def set(self, params: dict, data: dict):
        """Store results in cache"""
        try:
            key = self._get_cache_key(params)
            cache_path = self._get_cache_path(key)
            
            cache_data = {
                'timestamp': time.time(),
                'data': data
            }
            
            with cache_path.open('w') as f:
                json.dump(cache_data, f)
                
            logger.info(f"Cached data for key {key}")
                
        except Exception as e:
            logger.warning(f"Error writing to cache: {str(e)}")

class PDLApi:
    """People Data Labs API client for company data"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv('PDL_API_KEY')
        if not self.api_key:
            raise PDLError("PDL_API_KEY environment variable is required")
            
        self.base_url = "https://api.peopledatalabs.com/v5/company/search"
        self.headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key
        }
        self.logger = logging.getLogger(__name__)

    def search_companies(self, params: dict) -> List[Dict]:
        """
        Search for companies using PDL's Company Search API
        Uses Elasticsearch-style query parameters
        """
        try:
            # Construct the ES query based on parameters
            must_conditions = []
            
            # Location filter
            if params.get('locations'):
                must_conditions.append({
                    "terms": {
                        "location.country": params['locations']
                    }
                })
            
            # Employee count filter
            if params.get('min_employees') or params.get('max_employees'):
                employee_range = {}
                if params.get('min_employees'):
                    employee_range["gte"] = params['min_employees']
                if params.get('max_employees'):
                    employee_range["lte"] = params['max_employees']
                must_conditions.append({
                    "range": {
                        "employee_count": employee_range
                    }
                })
            
            # Funding stages filter
            if params.get('funding_stages'):
                must_conditions.append({
                    "terms": {
                        "funding_stages": params['funding_stages']
                    }
                })

            # Add location condition for Canada or the United States
            must_conditions.append({
                "bool": {
                    "should": [
                        {"term": {"location.country": "United States"}},
                        {"term": {"location.country": "Canada"}}
                    ]
                }
            })

            # Construct the final Elasticsearch query
            es_query = {
                "bool": {
                    "must": must_conditions
                }
            }
            
            # Prepare the search payload
            search_payload = {
                "query": es_query,
                "size": params.get('size', 100),
                "from": params.get('from', 0)
            }

            # Make the API request
            response = requests.post(
                f"{self.base_url}/company/search",
                headers=self.headers,
                json={"query": search_payload}
            )
            response.raise_for_status()
            data = response.json()
            
            # Process and clean the results
            companies = []
            for company in data.get('data', []):
                cleaned_company = {
                    'name': company.get('name', 'N/A'),
                    'website': company.get('website', 'N/A'),
                    'linkedin_url': company.get('linkedin_url', 'N/A'),
                    'total_employees': company.get('employee_count', 'N/A'),
                    'location': self._format_location(company.get('location.country', {})),
                    'industry': company.get('industry', 'N/A'),
                    'founded_year': company.get('founded', 'N/A'),
                    'company_type': company.get('type', 'N/A'),
                    'funding_stage': company.get('latest_funding_stage', 'N/A'),
                    'funding_total': self._format_funding(company.get('total_funding_raised')),
            
                }
                companies.append(cleaned_company)
            
            return companies

        except requests.exceptions.RequestException as e:
            self.logger.error(f"PDL API request failed: {str(e)}")
            raise PDLError(f"API request failed: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error processing PDL data: {str(e)}")
            raise PDLError(f"Data processing error: {str(e)}")

    def _format_location(self, location: Dict) -> str:
        """Format location data into a readable string"""
        if not location:
            return 'N/A'
        
        parts = []
        if location.get('locality'):
            parts.append(location['locality'])
        if location.get('region'):
            parts.append(location['region'])
        if location.get('country'):
            parts.append(location['country'])
            
        return ', '.join(parts) if parts else 'N/A'

    def _format_funding(self, amount: float) -> str:
        """Format funding amount with proper currency notation"""
        if not amount:
            return 'N/A'
        return f"${amount:,.0f}"

    def _format_latest_funding(self, funding_details: List) -> str:
        """Format latest funding round information"""
        if not funding_details:
            return 'N/A'
            
        # Sort by date and get the latest
        sorted_rounds = sorted(
            funding_details,
            key=lambda x: x.get('last_funding_date', ''),
            reverse=True
        )
        
        if not sorted_rounds:
            return 'N/A'
            
        latest = sorted_rounds[0]
        amount = latest.get('total_funding_raised')
        funding_type = latest.get('latest_funding_stage', 'N/A')
        
        if amount:
            return f"{funding_type} - ${amount:,.0f}"
        return funding_type

    def search_people(self, params: dict) -> List[Dict]:
        """
        Search for people using PDL's Person Search API
        
        Args:
            params: Dictionary of search parameters
            
        Returns:
            List of person records matching the search criteria
        """
        try:
            # The correct endpoint for person search
            url = "https://api.peopledatalabs.com/v5/person/search"
            
            # Log the request details for debugging
            logger.debug(f"API Request: POST {url}")
            logger.debug(f"Headers: {json.dumps(self.headers)}")
            logger.debug(f"Payload: {json.dumps(params)}")
            
            # Make the API request
            response = requests.post(url, headers=self.headers, json=params)
            
            # Check for API errors
            if response.status_code == 401:
                raise PDLError("Invalid API key or unauthorized access")
            elif response.status_code == 429:
                raise PDLError("API rate limit exceeded")
            elif response.status_code >= 400:
                error_msg = response.json().get('error', str(response.content))
                raise PDLError(f"API error ({response.status_code}): {error_msg}")
                
            response.raise_for_status()
            data = response.json()
            
            # Log the response for debugging
            logger.debug(f"API Response: {json.dumps(data)}")
            
            return data.get('data', [])
            
        except requests.exceptions.RequestException as e:
            raise PDLError(f"Request failed: {str(e)}")
        except json.JSONDecodeError:
            raise PDLError("Invalid JSON response from API")
        except Exception as e:
            raise PDLError(f"Unexpected error: {str(e)}")

class PDLTool:
    """Tool for interacting with the People Data Labs API"""
    
    def __init__(self, api_key):
        """Initialize the PDL tool with API key"""
        self.api_key = api_key
        self.base_url = "https://api.peopledatalabs.com/v5"
        self.headers = {"X-Api-Key": api_key}
        self.cache = {}
        self.cache_ttl = 3600  # 1 hour
        self.logger = logging.getLogger(__name__)

    def _clean_domain(self, domain):
        """Clean and standardize a domain string"""
        if not domain:
            return None
        
        # Remove protocol and www if present
        domain = domain.lower()
        domain = re.sub(r'^https?://', '', domain)
        domain = re.sub(r'^www\.', '', domain)
        
        # Remove any paths or query parameters
        domain = domain.split('/')[0]
        domain = domain.split('?')[0]
        
        return domain

    def get_company_details(self, company_name_or_domain):
        """Get company details from PDL using the Company Enrichment API"""
        cache_key = f"company_{company_name_or_domain}"
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if time.time() - cached_data['timestamp'] < self.cache_ttl:
                return cached_data['data']
        
        try:
            # Determine if input is likely a domain
            is_domain = '.' in company_name_or_domain and ' ' not in company_name_or_domain
            
            if is_domain:
                clean_domain = self._clean_domain(company_name_or_domain)
                self.logger.info(f"Searching for company by domain: {clean_domain}")
                params = {
                    "website": clean_domain
                }
            else:
                self.logger.info(f"Searching for company by name: {company_name_or_domain}")
                params = {
                    "name": company_name_or_domain
                }
            
            response = requests.get(
                "https://api.peopledatalabs.com/v5/company/enrich",
                headers=self.headers,
                params=params
            )
            
            if response.status_code == 404:
                self.logger.warning(f"Company not found: {company_name_or_domain}")
                return None
            elif response.status_code != 200:
                self.logger.error(f"PDL API error: {response.status_code} - {response.text}")
                return None
            
            company_data = response.json()
            
            # Clean up the website field
            if company_data.get('website'):
                company_data['website'] = self._clean_domain(company_data['website'])
            
            # Cache the result
            self.cache[cache_key] = {
                'timestamp': time.time(),
                'data': company_data
            }
            
            return company_data
            
        except Exception as e:
            self.logger.error(f"Error getting company details: {str(e)}")
            self.logger.error(traceback.format_exc())
            return None

    def get_engineering_team_info(self, company_domain):
        """Get engineering team information for a company"""
        try:
            clean_domain = self._clean_domain(company_domain)
            if not clean_domain:
                return {"error": "Invalid domain provided"}

            self.logger.info(f"Getting engineering team info for domain: {clean_domain}")
            
            # First get basic company info
            company_info = self.get_company_details(clean_domain)
            if not company_info:
                return {"error": f"Could not find company info for domain: {clean_domain}"}

            # Search for engineering leaders
            leaders_query = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"current_employer_domain": clean_domain}},
                            {
                                "bool": {
                                    "should": [
                                        {"match": {"job_title_role": "engineering"}},
                                        {"match": {"job_title_role": "developer"}},
                                        {"match": {"job_title_role": "architect"}}
                                    ],
                                    "minimum_should_match": 1
                                }
                            },
                            {
                                "bool": {
                                    "should": [
                                        {"match": {"job_title_level": "director"}},
                                        {"match": {"job_title_level": "head"}},
                                        {"match": {"job_title_level": "lead"}},
                                        {"match": {"job_title_level": "senior"}},
                                        {"match": {"job_title_level": "principal"}},
                                        {"match": {"job_title_level": "manager"}},
                                        {"match": {"job_title_level": "vp"}},
                                        {"match": {"job_title_level": "chief"}}
                                    ],
                                    "minimum_should_match": 1
                                }
                            }
                        ]
                    }
                },
                "size": 10
            }

            # Get engineering leaders
            leaders_response = requests.post(
                f"{self.base_url}/person/search",
                headers=self.headers,
                json=leaders_query
            )
            
            if leaders_response.status_code != 200:
                self.logger.error(f"Error fetching engineering leaders: {leaders_response.status_code} - {leaders_response.text}")
                return {"error": "Failed to fetch engineering leaders"}

            leaders_data = leaders_response.json()
            
            # Get total engineering headcount
            eng_count_query = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"current_employer_domain": clean_domain}},
                            {
                                "bool": {
                                    "should": [
                                        {"match": {"job_title_role": "engineering"}},
                                        {"match": {"job_title_role": "developer"}},
                                        {"match": {"job_title_role": "architect"}}
                                    ],
                                    "minimum_should_match": 1
                                }
                            }
                        ]
                    }
                },
                "size": 0
            }

            eng_count_response = requests.post(
                f"{self.base_url}/person/search",
                headers=self.headers,
                json=eng_count_query
            )

            if eng_count_response.status_code != 200:
                self.logger.error(f"Error fetching engineering count: {eng_count_response.status_code} - {eng_count_response.text}")
                return {"error": "Failed to fetch engineering headcount"}

            eng_count_data = eng_count_response.json()
            
            # Calculate engineering percentage
            total_employees = company_info.get('employee_count', 0)
            engineering_count = eng_count_data.get('total', 0)
            engineering_percentage = (engineering_count / total_employees * 100) if total_employees > 0 else 0

            # Process and deduplicate engineering leaders
            seen_leaders = set()
            unique_leaders = []
            
            for leader in leaders_data.get('data', []):
                name = leader.get('full_name', '')
                if name and name not in seen_leaders:
                    seen_leaders.add(name)
                    unique_leaders.append({
                        'name': name,
                        'title': leader.get('job_title', ''),
                        'location': self._format_location(leader),
                        'linkedin_url': leader.get('linkedin_url', ''),
                        'work_email': leader.get('work_email', '')
                    })

            return {
                "company_info": company_info,
                "engineering_leaders": unique_leaders,
                "engineering_count": engineering_count,
                "engineering_percentage": round(engineering_percentage, 1),
                "total_employees": total_employees
            }

        except Exception as e:
            self.logger.error(f"Error in get_engineering_team_info: {str(e)}")
            self.logger.error(traceback.format_exc())
            return {"error": f"Internal error: {str(e)}"}

    def _format_location(self, person_data):
        """Format location data into a readable string"""
        location_parts = []
        
        if person_data.get('city'):
            location_parts.append(person_data['city'])
        
        if person_data.get('region'):
            location_parts.append(person_data['region'])
        
        if person_data.get('country'):
            if person_data['country'] != 'United States' or not location_parts:
                location_parts.append(person_data['country'])
        
        return ', '.join(location_parts) if location_parts else 'Location unknown'

    def _format_funding(self, amount):
        """Format funding amounts with proper currency notation"""
        if not amount or amount == 0:
            return 'N/A'
        
        if amount >= 1_000_000_000:
            return f'${amount / 1_000_000_000:.1f}B'
        elif amount >= 1_000_000:
            return f'${amount / 1_000_000:.1f}M'
        elif amount >= 1_000:
            return f'${amount / 1_000:.1f}K'
        else:
            return f'${amount:,.0f}'

    def search_companies(self, min_employees=None, max_employees=None, funding_stages=None, page=1, size=10):
        """
        Search for companies using PDL's Company Search API
        Uses Elasticsearch-style query parameters
        
        Args:
            min_employees (int, optional): Minimum number of employees
            max_employees (int, optional): Maximum number of employees
            funding_stages (list, optional): List of funding stages to filter by
            page (int, optional): Page number for pagination (default: 1)
            size (int, optional): Number of results per page (default: 10)
        """
        try:
            # Construct ES query based on parameters
            must_conditions = []
            
            # Employee count filter
            if min_employees is not None or max_employees is not None:
                employee_range = {}
                if min_employees is not None:
                    employee_range["gte"] = min_employees
                if max_employees is not None:
                    employee_range["lte"] = max_employees
                must_conditions.append({
                    "range": {
                        "employee_count": employee_range
                    }
                })
            
            # Funding stages filter
            if funding_stages:
                must_conditions.append({
                    "terms": {
                        "latest_funding_stage": funding_stages
                    }
                })

            # Add location condition for Canada or United States
            location_terms = [
                {"term": {"location.country": "United States"}},
                {"term": {"location.country": "Canada"}}
            ]
            must_conditions.append({
                "bool": {
                    "should": location_terms
                }
            })

            # Construct the final Elasticsearch query
            search_payload = {
                "query": {
                    "bool": {
                        "must": must_conditions
                    }
                },
                "size": size,
                "from": (page - 1) * size  # Calculate offset based on page number
            }

            # Make the API request
            response = requests.post(
                "https://api.peopledatalabs.com/v5/company/search",
                headers=self.headers,
                json=search_payload
            )
            
            if response.status_code != 200:
                self.logger.error(f"PDL API error: {response.status_code} - {response.text}")
                return None
            
            data = response.json()
            
            # Process and clean the results
            companies = []
            for company in data.get('data', []):
                cleaned_company = {
                    'name': company.get('name', 'N/A'),
                    'website': company.get('website', 'N/A'),
                    'linkedin_url': company.get('linkedin_url', 'N/A'),
                    'total_employees': company.get('employee_count', 'N/A'),
                    'location': self._format_location(company.get('location', {})),
                    'industry': company.get('industry', 'N/A'),
                    'founded_year': company.get('founded', 'N/A'),
                    'company_type': company.get('type', 'N/A'),
                    'funding_stage': company.get('latest_funding_stage', 'N/A'),
                    'funding_total': self._format_funding(company.get('total_funding_raised'))
                }
                companies.append(cleaned_company)
            
            return {
                'total': data.get('total', 0),
                'companies': companies,
                'page': page,
                'size': size
            }

        except Exception as e:
            self.logger.error(f"Error searching companies: {str(e)}")
            self.logger.error(traceback.format_exc())
            return None

if __name__ == "__main__":
    # Get user input for employee count range
    try:
        min_employees_input = input("Enter minimum number of employees (press Enter to skip): ")
        min_employees = int(min_employees_input) if min_employees_input.strip() else None
        
        max_employees_input = input("Enter maximum number of employees (press Enter to skip): ")
        max_employees = int(max_employees_input) if max_employees_input.strip() else None
        
        # Initialize the tool and run the search
        tool = PDLTool()
        results = tool.search_companies(min_employees, max_employees)
        
        # Print results
        print(f"\nFound {results['total']} companies")
        for company in results['companies']:
            print(f"\nCompany: {company['name']}")
            print(f"Website: {company['website']}")
            print(f"Employees: {company['total_employees']}")
            print(f"Location: {company['location']}")
            print(f"Industry: {company['industry']}")
            print(f"Funding Stage: {company['funding_stage']}")
            print(f"Total Funding: {company['funding_total']}")
            
    except ValueError:
        print("Invalid input. Please enter valid numbers.")
    except Exception as e:
        print(f"An error occurred: {str(e)}") 