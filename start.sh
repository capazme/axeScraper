nohup python src/pipeline.py > pipeline.log 2>&1 &
ps aux | grep src/pipeline.py
