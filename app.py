from flask import Flask, render_template, request, jsonify, send_file
from tools.pdl_tool import PDLTool
from typing import Dict, Optional, List
from dotenv import load_dotenv
import os
import logging
import json
import traceback
from pathlib import Path
from datetime import datetime
import csv
from io import StringIO, BytesIO
import time

# Set up logging with more detail
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def handle_error(e: Exception) -> tuple:
    """Handle exceptions and return appropriate error response"""
    error_details = {
        'error': str(e),
        'type': type(e).__name__,
        'trace': traceback.format_exc()
    }
    logger.error(f"Application error: {json.dumps(error_details, indent=2)}")
    return jsonify(error_details), 500

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

try:
    # Load API keys
    load_dotenv()

    # Initialize tools
    pdl_tool = PDLTool()

    # Add after app initialization
    TEST_MODE = os.getenv('TEST_MODE', 'false').lower() == 'true'
    CACHE_DIR = Path('test_data')
    
    logger.info("Application initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize application: {str(e)}")
    logger.error(traceback.format_exc())
    raise

def load_test_data(company_name: str) -> Optional[Dict]:
    """Load test data for a company"""
    try:
        cache_file = CACHE_DIR / f"{company_name.lower().replace(' ', '_')}.json"
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading test data: {str(e)}")
    return None

def save_test_data(company_name: str, data: Dict):
    """Save test data for a company"""
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        cache_file = CACHE_DIR / f"{company_name.lower().replace(' ', '_')}.json"
        with open(cache_file, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving test data: {str(e)}")

@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')

@app.route('/authenticate', methods=['POST'])
def authenticate():
    """Check API key validity"""
    try:
        # Test connection using authenticate method
        pdl_result = pdl_tool.authenticate()
        
        return jsonify({
            "pdl": pdl_result,
        })
    except Exception as e:
        return handle_error(e)

@app.route('/search_companies', methods=['POST'])
def search_companies():
    """Search for companies based on criteria"""
    try:
        data = request.get_json()
        
        # Extract search parameters
        min_employees = data.get('min_employees')
        max_employees = data.get('max_employees')
        funding_stages = data.get('funding_stages', [])
        page = data.get('page', 1)
        page_size = data.get('size', 10)
        
        # Validate numeric parameters
        if min_employees and not str(min_employees).isdigit():
            return jsonify({"error": "min_employees must be a positive number"}), 400
        if max_employees and not str(max_employees).isdigit():
            return jsonify({"error": "max_employees must be a positive number"}), 400
        
        # Convert to integers if present
        min_employees = int(min_employees) if min_employees else None
        max_employees = int(max_employees) if max_employees else None
        
        # Perform the search
        results = pdl_tool.search_companies(
            min_employees=min_employees,
            max_employees=max_employees,
            funding_stages=funding_stages,
            page=page,
            size=page_size
        )
        
        return jsonify(results)
        
    except Exception as e:
        app.logger.error(f"Error during company search: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/analyze_company', methods=['POST'])
def analyze_company():
    """Analyze a company using PDL data"""
    try:
        data = request.json
        company_name = data.get('company_name')
        company_domain = data.get('company_domain')
        
        if not company_name and not company_domain:
            return jsonify({"error": "Either company_name or company_domain is required"}), 400

        # Get company data from PDL
        company_data = None
        if company_name:
            company_data = pdl_tool.get_company_details(company_name)
            
            # Check if we got a valid response from PDL
            if not company_data or not company_data.get('name'):
                return jsonify({"error": f"Could not find company data for: {company_name}"}), 404
                
            # Extract domain from website if available
            if company_data.get('website'):
                company_domain = company_data.get('website', '').replace('https://', '').replace('http://', '').split('/')[0]
        
        # Only proceed with engineering team search if we have a valid company domain
        if company_domain:
            try:
                # Get engineering team data from PDL
                eng_data = pdl_tool.get_engineering_team(company_domain)
                
                # Generate personalized messages for engineering leaders
                messages = []
                for leader in eng_data.get('engineering_leaders', []):
                    message = pdl_tool.generate_personalized_message(
                        leader, 
                        eng_data.get('engineering_percentage', 0)
                    )
                    messages.append({
                        "leader": leader,
                        "message": message
                    })
                
                # Combine the data
                result = {
                    "company": company_data,
                    "engineering": eng_data,
                    "personalized_messages": messages
                }
                
                return jsonify(result)
            except Exception as pdl_error:
                logger.error(f"PDL API error: {str(pdl_error)}")
                # Return just the PDL data if engineering team search fails
                return jsonify({
                    "company": company_data,
                    "engineering": {"error": "Could not retrieve engineering data"},
                    "personalized_messages": []
                })
        else:
            # Return just the PDL data if we couldn't extract a domain
            return jsonify({
                "company": company_data,
                "engineering": {"error": "Could not determine company domain"},
                "personalized_messages": []
            })

    except Exception as e:
        logger.error(f"Error analyzing company: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/export_companies', methods=['POST'])
def export_companies():
    """Export companies to CSV"""
    try:
        data = request.json or {}
        start_page = data.get('start_page', 1)
        
        # Initialize progress tracking
        app.config['export_status'] = f'Starting from page {start_page}'
        app.config['export_current_page'] = start_page - 1
        app.config['export_total_companies'] = 0
        app.config['export_last_updated'] = datetime.now().isoformat()
        app.config['last_successful_page'] = 0

        all_companies = []
        page = start_page
        per_page = 100  # PDL's recommended page size
        
        logger.info(f"Starting company export with pagination from page {start_page}")
        
        while True:
            # Update progress
            app.config['export_current_page'] = page
            app.config['export_total_companies'] = len(all_companies)
            app.config['export_last_updated'] = datetime.now().isoformat()
            
            try:
                # Get companies for current page
                logger.info(f"Fetching page {page}")
                
                results = pdl_tool.search_companies(
                    min_employees=50,  # Adjust these filters as needed
                    max_employees=1000,
                    funding_stages=['series_a', 'series_b', 'series_c'],
                    page=page,
                    size=per_page
                )
                
                companies = results.get('companies', [])
                
                if not companies:
                    app.config['last_successful_page'] = page - 1
                    app.config['export_status'] = 'Completed - No more results'
                    break
                
                all_companies.extend(companies)
                logger.info(f"Fetched page {page}, got {len(companies)} companies. Total: {len(all_companies)}")
                
                if len(companies) < per_page:  # Last page
                    app.config['last_successful_page'] = page
                    app.config['export_status'] = 'Completed - All results retrieved'
                    break
                    
                page += 1
                app.config['last_successful_page'] = page - 1
                
                # Add a small delay between API calls
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error on page {page}: {str(e)}")
                app.config['export_status'] = f'Error on page {page}: {str(e)}'
                break

        if not all_companies:
            app.config['export_status'] = 'Completed - No companies found'
            return jsonify({
                'error': 'No companies found matching criteria',
                'last_successful_page': app.config['last_successful_page']
            }), 404

        # Create CSV in memory
        si = StringIO()
        writer = csv.DictWriter(si, fieldnames=[
            'name',
            'website',
            'linkedin_url',
            'total_employees',
            'engineering_percentage',
            'location',
            'industry',
            'founded_year',
            'funding_stage',
            'funding_total',
            'tech_stack',
            'description'
        ])
        
        writer.writeheader()
        
        for company in all_companies:
            writer.writerow({
                'name': company.get('name', 'N/A'),
                'website': company.get('website', 'N/A'),
                'linkedin_url': company.get('linkedin_url', 'N/A'),
                'total_employees': company.get('total_employees', 'N/A'),
                'engineering_percentage': company.get('engineering_percentage', 'N/A'),
                'location': company.get('location', 'N/A'),
                'industry': company.get('industry', 'N/A'),
                'founded_year': company.get('founded_year', 'N/A'),
                'funding_stage': company.get('funding_stage', 'N/A'),
                'funding_total': company.get('funding_total', 'N/A'),
                'tech_stack': ', '.join(company.get('tech_stack', [])),
                'description': company.get('description', 'N/A')
            })

        # Convert to BytesIO for binary mode
        output = si.getvalue().encode('utf-8')
        output_bio = BytesIO()
        output_bio.write(output)
        output_bio.seek(0)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'companies_export_{timestamp}.csv'
        
        return send_file(
            output_bio,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        error_msg = f"Export failed: {str(e)}"
        logger.error(error_msg)
        app.config['export_status'] = f'Error: {error_msg}'
        return handle_error(e)

@app.route('/export_status', methods=['GET'])
def export_status():
    """Get detailed export status"""
    status = {
        'current_page': app.config.get('export_current_page', 0),
        'total_companies': app.config.get('export_total_companies', 0),
        'status': app.config.get('export_status', 'Not started'),
        'last_updated': app.config.get('export_last_updated', None),
        'last_successful_page': app.config.get('last_successful_page', 0)
    }
    return jsonify(status)

@app.route('/export')
def export_page():
    """Serve the export page"""
    return render_template('export.html')

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5001, debug=True)
    except Exception as e:
        logger.error(f"Failed to start server: {str(e)}")
        logger.error(traceback.format_exc())