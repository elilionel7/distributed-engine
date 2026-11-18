import time

def process_item(item):
    time.sleep(2)  # Simulate a slow task
    print(f"Processed: {item * 2}")