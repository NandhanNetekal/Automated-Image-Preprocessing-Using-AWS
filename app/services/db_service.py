import os
import pymysql
from dotenv import load_dotenv

load_dotenv()


def get_db_connection():
    try:
        connection = pymysql.connect(
            host=os.getenv("MYSQL_HOST"),
            user=os.getenv("MYSQL_USER"),
            password=os.getenv("MYSQL_PASSWORD"),
            database=os.getenv("MYSQL_DATABASE"),
            port=3306,
            cursorclass=pymysql.cursors.DictCursor
        )

        return connection
    
    except pymysql.MySQLError as error:
        print("MySQL Connection Error:", error)
        return None
def save_image_metadata(filename, s3_key, file_size, width, height):
    connection = get_db_connection()

    if connection is None:
        return None

    try:
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO images
                (filename, s3_key, file_size, image_width, image_height)
                VALUES (%s, %s, %s, %s, %s)
            """

            cursor.execute(
                sql,
                (filename, s3_key, file_size, width, height)
            )

            image_id = cursor.lastrowid
            connection.commit()

            return image_id

    except pymysql.MySQLError as error:
        connection.rollback()
        print("Image Metadata Error:", error)
        return None

    finally:
        connection.close()
        
def save_processing_history(
    image_id,
    operation,
    processed_filename,
    processed_s3_key
):
    connection = get_db_connection()

    if connection is None:
        return False

    try:
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO processing_history
                (image_id, operation, processed_filename, processed_s3_key)
                VALUES (%s, %s, %s, %s)
            """

            cursor.execute(
                sql,
                (
                    image_id,
                    operation,
                    processed_filename,
                    processed_s3_key
                )
            )

            connection.commit()
            return True

    except pymysql.MySQLError as error:
        connection.rollback()
        print("Processing History Error:", error)
        return False

    finally:
        connection.close()