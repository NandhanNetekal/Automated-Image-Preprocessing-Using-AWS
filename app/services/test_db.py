from app.services.db_service import get_db_connection

connection = get_db_connection()

if connection:
    print("MySQL Database Connected Successfully!")

    connection.close()
else:
    print("MySQL Database Connection Failed!")
    