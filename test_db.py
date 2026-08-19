import psycopg2

conn = psycopg2.connect(
    "postgresql://postgres.qmxarkexrjcfdaciohtt:Vansh%40%23123456vrc@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
)

print("Connected!")
conn.close()