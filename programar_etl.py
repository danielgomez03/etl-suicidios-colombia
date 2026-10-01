import time

import schedule

from main import run_pipeline

schedule.every().day.at("02:00").do(run_pipeline)   # o: schedule.every(10).minutes.do(...)

while True:
    schedule.run_pending()
    time.sleep(30)
