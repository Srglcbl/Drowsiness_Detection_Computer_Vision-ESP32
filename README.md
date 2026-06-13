🚗 #Driver Drowsiness Detection System Using YOLOv8 and ESP32#

A real-time driver drowsiness detection system based on Computer Vision and Deep Learning using YOLOv8, integrated with ESP32 for early warning alerts.

#📖 Overview

Driver drowsiness is one of the major causes of traffic accidents worldwide. This project aims to detect signs of drowsiness in real time by analyzing:

#👁️ Eye Condition (Open / Closed)
#😴 Yawning Behavior (Yawn / Non-Yawn)

When drowsiness indicators exceed predefined thresholds, the system sends a signal to an ESP32 microcontroller, which activates a buzzer and displays warning information on an LCD screen.

#🎯 Features
Real-time driver monitoring using webcam
YOLOv8-based object detection
Multi-class detection:
Open Eye
Closed Eye
Yawn
Non-Yawn
ESP32 integration
Audible warning system using buzzer
LCD status display
Low-latency detection suitable for safety applications

#🏗️ System Architecture
<img width="634" height="346" alt="image" src="https://github.com/user-attachments/assets/89d88181-fba0-4362-8494-1597c619c6e9" />

<img width="414" height="601" alt="image" src="https://github.com/user-attachments/assets/0072b47b-9637-4853-bd2a-4720169a5100" />

#🧠 Detection Workflow
Webcam captures driver's face.
YOLOv8 detects:
Open Eyes
Closed Eyes
Yawning
Non-Yawning
System calculates:
Eye closure duration
Yawning frequency
Decision logic determines driver state.
If drowsiness is detected:
ESP32 activates buzzer.
LCD displays warning message.
System continues monitoring in real time.

#📊 Dataset

This project uses:

Public Dataset
Driver Drowsiness Dataset (DDD) from Kaggle
More than 41,000 facial images
Custom Dataset

Collected using webcam under real driving simulation conditions.

Classes:

<img width="791" height="225" alt="image" src="https://github.com/user-attachments/assets/09d41f4f-fa9a-40e4-bc01-51b192bda3de" />

#📈 Performance
<img width="817" height="398" alt="image" src="https://github.com/user-attachments/assets/0ac90344-6aac-4cc7-bea3-00c9dd894fb1" />

#🛠️ Hardware Components
ESP32
Webcam
16x2 LCD (I2C)
Buzzer
Push Button
Personal Computer / Laptop
