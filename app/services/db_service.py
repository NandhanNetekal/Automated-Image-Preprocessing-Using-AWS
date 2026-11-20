import os
import pymysql
from dotenv import load_dotenv

load_dotenv()


def get_db_connection():
    try:
        return pymysql.connect(
            host=os.getenv("MYSQL_HOST"),
            user=os.getenv("MYSQL_USER"),
            password=os.getenv("MYSQL_PASSWORD"),
            database=os.getenv("MYSQL_DATABASE"),
            port=3306,
            cursorclass=pymysql.cursors.DictCursor
        )
    except pymysql.MySQLError as error:
        print("MySQL Connection Error:", error)
        return None


def save_image_metadata(filename, s3_key, file_size, width, height):
    connection = get_db_connection()
    if connection is None:
        return None

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO images
                (filename, s3_key, file_size, image_width, image_height)
                VALUES (%s, %s, %s, %s, %s)
                """,
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


def replace_processing_history(image_id, records):
    """Store only the operations generated in the latest run for an image."""
    connection = get_db_connection()
    if connection is None:
        return False

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM processing_history WHERE image_id = %s",
                (image_id,)
            )

            if records:
                cursor.executemany(
                    """
                    INSERT INTO processing_history
                    (image_id, operation, processed_filename, processed_s3_key)
                    VALUES (%s, %s, %s, %s)
                    """,
                    [
                        (
                            image_id,
                            item["operation"],
                            item["processed_filename"],
                            item["processed_s3_key"]
                        )
                        for item in records
                    ]
                )

        connection.commit()
        return True
    except pymysql.MySQLError as error:
        connection.rollback()
        print("Processing History Replacement Error:", error)
        return False
    finally:
        connection.close()


def get_processing_history_keys():
    """Return S3 keys that belong to the currently recorded outputs."""
    connection = get_db_connection()
    if connection is None:
        return set()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT processed_s3_key FROM processing_history"
            )
            rows = cursor.fetchall()

        return {
            row["processed_s3_key"]
            for row in rows
            if row.get("processed_s3_key")
        }
    except pymysql.MySQLError as error:
        print("Processing History Retrieval Error:", error)
        return set()
    finally:
        connection.close()
