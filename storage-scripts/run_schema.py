#!/usr/bin/env python3
"""
Quick script to execute the SQL schema file
"""
import psycopg2

# Database connection
conn = psycopg2.connect(
    host='localhost',
    database='PPL-AI',
    user='postgres',
    password='shreyaan999!',
    port=5432
)

# Read and execute SQL file
with open('export_data_schema.sql', 'r') as f:
    sql = f.read()

cursor = conn.cursor()
cursor.execute(sql)
conn.commit()

print("✓ Schema created successfully!")

cursor.close()
conn.close()
