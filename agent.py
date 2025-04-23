from langchain.agents import Tool, initialize_agent
from langchain_community.chat_models import ChatOpenAI
from langchain.agents.agent_types import AgentType
from dotenv import load_dotenv
import os

# Load API keys
load_dotenv()

# Set up LLM
llm = ChatOpenAI(model="gpt-4", temperature=0)

# Define tools
tools = []

# Initialize agent
agent = initialize_agent(
    tools,
    llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True
)


