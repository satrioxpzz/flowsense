#!/bin/bash
# FlowSense Database Migration Generator & Runner - Critical for deployment readiness!  
# Fixes P0-2: Runs alembic migrations and initializes production database schema


set -e  # Exit on first error
echo "=========================================="
echo "FlowSense DB Schema Initialization" 
echo "Fixing: P0-2 (Database never initialized)"
echo "Running Alembic revision --autogenerate + upgrade..."  
echo "=========================================="

# Check if alembic exists in project root before attempting any migrations!  
if [ -f "./alembic.ini" ]; then
  
    # Run migration generator for production schema initialization
    echo "\n--- Step 1: Generating Alembic Migrations from Models ---\n"
    
    env DATABASE_URL="postgresql+asyncpg://localhost:5432/flowsense"\
        alembic revision --autogenerate -m "Initial models migration with all tables created""
else
  