# Market Research Agent

A tool for market research and lead generation using People Data Labs (PDL) API. This tool helps identify companies and their technical employees for targeted outreach.

## Features

- Search companies by employee count and funding status
- Filter companies in Canada and United States
- Cache API results for improved performance
- Analyze technical workforce within companies
- Generate personalized email templates for outreach

## Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/market-research-agent.git
cd market-research-agent
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the root directory and add your PDL API key:
```
PDL_API_KEY=your_api_key_here
```

## Usage

1. Run the application:
```bash
python app.py
```

2. Use the web interface to:
   - Search for companies based on employee count
   - View company details and technical workforce analysis
   - Generate personalized outreach emails

## Project Structure

```
market-research-agent/
├── app.py                 # Main application file
├── tools/
│   ├── pdl_tool.py       # PDL API integration
│   └── __init__.py
├── templates/            # HTML templates
├── static/              # Static assets
├── cache/               # Cached API responses
└── requirements.txt     # Project dependencies
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details. 