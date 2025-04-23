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
    
    def __init__(self, cache_dir: str = ".cache", ttl_hours: int = 4):
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
                
            logger.info(f"Found valid cache for key {key}, companies: {len(cached_data['data'].get('companies', []))}")
            return cached_data['data']
            
        except Exception as e:
            logger.warning(f"Error reading cache: {str(e)}")
            return None
            
    def set(self, params: dict, data: dict):
        """Store results in cache"""
        try:
            key = self._get_cache_key(params)
            cache_path = self._get_cache_path(key)
            
            companies_count = len(data.get('companies', []))
            logger.info(f"Caching {companies_count} companies for key {key}")
            
            cache_data = {
                'timestamp': time.time(),
                'data': data
            }
            
            with cache_path.open('w') as f:
                json.dump(cache_data, f)
                
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
    """Tool for interacting with People Data Labs API"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize PDL tool with API key"""
        self.api_key = api_key or os.getenv('PDL_API_KEY')
        if not self.api_key:
            raise ValueError("PDL API key not found. Please set PDL_API_KEY environment variable.")
        
        self.base_url = "https://api.peopledatalabs.com"
        self.cache = Cache(cache_dir="cache", ttl_hours=24)  # Initialize cache with 24 hour TTL

    def search_companies(
        self,
        min_employees: Optional[int] = None,
        max_employees: Optional[int] = None,
        funding_stages: Optional[List[str]] = None,
        page: int = 1,
        size: int = 10
    ) -> Dict:
        """
        Search for companies based on criteria using PDL's ES query format.
        Results are cached to avoid unnecessary API calls.
        
        Args:
            min_employees: Minimum number of employees
            max_employees: Maximum number of employees
            page: Page number for pagination
            size: Number of results per page
            
        Returns:
            Dict containing search results and metadata
        """
        try:
            # Build ES query
            must_conditions = []
            
            # Add employee count range if provided
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
            
            # Add funding condition
            must_conditions.append({
                "exists": {
                    "field": "total_funding_raised"
                }
            })
            
            # Add location condition for Canada or United States using terms query
            must_conditions.append({
                "terms": {
                    "location.country": ["canada", "united states"]
                }
            })
            
            # Construct the final query
            query = {
                "query": {
                    "bool": {
                        "must": must_conditions
                    }
                },
                "size": size,
                "from": (page - 1) * size
            }
            
            # Create cache parameters
            cache_params = {
                "query": query,
                "page": page,
                "size": size
            }
            
            # Try to get results from cache first
            cached_results = self.cache.get(cache_params)
            if cached_results:
                logger.info("Retrieved results from cache")
                return cached_results
            
            logger.debug(f"ES Query: {json.dumps(query, indent=2)}")
            
            # Make the API request with proper headers
            headers = {
                "Content-Type": "application/json",
                "X-Api-Key": self.api_key
            }
            
            response = requests.post(
                f"{self.base_url}/v5/company/search",
                headers=headers,
                json=query
            )
            
            # Log the response status and content
            logger.debug(f"Response Status Code: {response.status_code}")
            
            # Check for HTTP errors
            if response.status_code != 200:
                logger.error(f"API Error Response: {response.text}")
                response.raise_for_status()
            
            # Process the response
            data = response.json()
            companies_data = data.get('data', [])
            total = data.get('total', 0)
            
            logger.info(f"API returned {total} total companies, {len(companies_data)} in current page")
            
            # Format the results
            formatted_results = {
                "total": total,
                "companies": [self._format_company(company) for company in companies_data],
                "page": page,
                "size": size
            }
            
            # Cache the results
            self.cache.set(cache_params, formatted_results)
            logger.info("Cached new results")
            
            return formatted_results
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP Error: {str(e)}")
            logger.error(f"Response content: {e.response.text if hasattr(e, 'response') else 'No response content'}")
            raise
        except Exception as e:
            logger.error(f"Error searching companies: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise Exception(f"Search request failed: {str(e)}")

    def _format_company(self, company: Dict) -> Dict:
        """Format company data for consistent output"""
        return {
            'name': company.get('name'),
            'website': company.get('website'),
            'total_employees': company.get('employee_count'),
            'location': company.get('location', {}).get('country'),
            'industry': company.get('industry'),
            'funding_stage': company.get('latest_funding_stage'),
            'total_funding': company.get('total_funding_raised')
        }

    def clear_cache(self):
        """Clear the cache to force fresh API calls"""
        self.cache.clear()

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
            print(f"Total Funding: {company['total_funding']}")
            
    except ValueError:
        print("Invalid input. Please enter valid numbers.")
    except Exception as e:
        print(f"An error occurred: {str(e)}") 