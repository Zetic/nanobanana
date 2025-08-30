#!/bin/bash

# Nano Banana Discord Bot Launcher
# This script provides an easy way to run the Discord bot with automatic checks

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to pause before exit (prevents console from closing immediately)
pause_before_exit() {
    local exit_code=${1:-1}
    
    # Only pause if running interactively (not in automated environments)
    if [[ -t 0 ]] && [[ -t 1 ]]; then
        echo
        echo "Press any key to close this window..."
        read -n 1 -s
    fi
    
    exit $exit_code
}

# Function to check Python version
check_python() {
    print_info "Checking Python installation..."
    
    if command_exists python3; then
        PYTHON_CMD="python3"
    elif command_exists python; then
        # Check if python is Python 3
        if python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null; then
            PYTHON_CMD="python"
        else
            print_error "Python 3.8+ is required, but found Python 2 or older version"
            pause_before_exit 1
        fi
    else
        print_error "Python is not installed or not in PATH"
        print_info "Please install Python 3.8+ from https://python.org"
        pause_before_exit 1
    fi
    
    # Get Python version
    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1)
    print_success "Found $PYTHON_VERSION"
}

# Function to check if pip is available
check_pip() {
    print_info "Checking pip installation..."
    
    if command_exists pip3; then
        PIP_CMD="pip3"
    elif command_exists pip; then
        PIP_CMD="pip"
    else
        print_error "pip is not installed or not in PATH"
        print_info "Please install pip: https://pip.pypa.io/en/stable/installation/"
        pause_before_exit 1
    fi
    
    print_success "pip is available"
}

# Function to check and install dependencies
check_dependencies() {
    print_info "Checking dependencies..."
    
    if [ ! -f "requirements.txt" ]; then
        print_error "requirements.txt not found!"
        pause_before_exit 1
    fi
    
    # Try to import required modules
    if ! $PYTHON_CMD -c "import discord, google.genai, PIL, dotenv, aiohttp" 2>/dev/null; then
        print_warning "Some dependencies are missing"
        read -p "Would you like to install dependencies now? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            print_info "Installing dependencies..."
            $PIP_CMD install -r requirements.txt
            print_success "Dependencies installed successfully"
        else
            print_error "Dependencies are required to run the bot"
            print_info "Run: $PIP_CMD install -r requirements.txt"
            pause_before_exit 1
        fi
    else
        print_success "All dependencies are installed"
    fi
}

# Function to check environment configuration
check_environment() {
    print_info "Checking environment configuration..."
    
    if [ ! -f ".env" ]; then
        print_warning ".env file not found"
        if [ -f ".env.example" ]; then
            print_info "Creating .env from .env.example..."
            cp .env.example .env
            print_warning "Please edit .env file with your actual tokens:"
            print_info "  - DISCORD_TOKEN: Your Discord bot token"
            print_info "  - GOOGLE_API_KEY: Your Google GenAI API key"
            print_info ""
            print_info "After editing .env, run this script again"
            pause_before_exit 1
        else
            print_error ".env.example file not found"
            print_info "Please create a .env file with:"
            print_info "  DISCORD_TOKEN=your_discord_bot_token_here"
            print_info "  GOOGLE_API_KEY=your_google_api_key_here"
            pause_before_exit 1
        fi
    fi
    
    # Check if tokens are set (not just placeholder values)
    if grep -q "your_discord_bot_token_here" .env || grep -q "your_google_api_key_here" .env; then
        print_warning "Default placeholder values found in .env"
        print_info "Please edit .env file with your actual tokens:"
        print_info "  - DISCORD_TOKEN: Your Discord bot token"
        print_info "  - GOOGLE_API_KEY: Your Google GenAI API key"
        pause_before_exit 1
    fi
    
    print_success "Environment configuration looks good"
}

# Function to run the bot
run_bot() {
    print_info "Starting Nano Banana Discord Bot..."
    print_info "Press Ctrl+C to stop the bot"
    echo
    
    # Run the bot
    $PYTHON_CMD main.py
    
    # If we reach here, the bot has stopped normally
    echo
    print_info "Bot has stopped"
    
    # Pause before exit only if running interactively
    if [[ -t 0 ]] && [[ -t 1 ]]; then
        echo "Press any key to close this window..."
        read -n 1 -s
    fi
}

# Main script execution
main() {
    echo "🍌 Nano Banana Discord Bot Launcher"
    echo "======================================"
    echo
    
    # Check if we're in the right directory
    if [ ! -f "main.py" ]; then
        print_error "main.py not found. Please run this script from the nanobanana directory"
        pause_before_exit 1
    fi
    
    # Perform all checks
    check_python
    check_pip
    check_dependencies
    check_environment
    
    echo
    print_success "All checks passed! Starting the bot..."
    echo
    
    # Run the bot
    run_bot
}

# Handle Ctrl+C gracefully
trap 'echo; print_info "Bot stopped by user"; if [[ -t 0 ]] && [[ -t 1 ]]; then echo "Press any key to close this window..."; read -n 1 -s; fi; exit 0' INT

# Run main function
main "$@"