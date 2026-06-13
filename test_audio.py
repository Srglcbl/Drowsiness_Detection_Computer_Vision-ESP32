from playsound import playsound
import os
import time

print("Testing audio...")
current_dir = os.getcwd()
file_path = os.path.join(current_dir, 'alarm.mp3')
print(f"File path: {file_path}")

if os.path.exists(file_path):
    print("File exists. Attempting to play...")
    try:
        playsound(file_path)
        print("Success!")
    except Exception as e:
        print(f"Error: {e}")
else:
    print("File does not exist!")
