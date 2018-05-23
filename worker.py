import pymongo
from pymongo import MongoClient
import gridfs
import time
import io
import zipfile
import tempfile
import os
from bson import ObjectId
import subprocess 
import sys

client = pymongo.MongoClient('localhost',
        username='rooty',
        password='passy')

db = client.my_db
queue = db.queue

try:
    while True:
        time.sleep(0.01)
        job = None
        # 
        with client.start_session(causal_consistency=True) as session:
            grid_out = queue.find_one({"status": "waiting"}, no_cursor_timeout=True, session=session)

            if grid_out is not None:
                # Set the flag (atomically) - I own the job now
                queue.update_one({'_id': grid_out['_id']}, {'$set': {'status': 'running'}}, session=session)
                job = grid_out

        if job is not None:

            with tempfile.TemporaryDirectory() as tmpdirname:
                # Write the Dockerfile from the job spec
                with open(os.path.join(tmpdirname, "Dockerfile"),'w') as fp:
                    fp.write(job['Dockerfile'])
                    
                # Get the input data and write to file
                fs = gridfs.GridFS(db)
                file_ = fs.get(ObjectId(job['data_id']))  
                fname = os.path.join(tmpdirname, file_.filename)
                with open(fname, 'wb') as fp:
                    fp.write(file_.read())
                    
                # Unpack the data to the root of the temporary folder
                with zipfile.ZipFile(fname) as myzip:
                    myzip.printdir()
                    myzip.extractall(path=tmpdirname)
                    
                # 
                subprocess.check_call('docker image build -t job .', shell=True, cwd=tmpdirname, stdout = sys.stdout, stderr= sys.stderr)
                
                subprocess.check_call('docker container run job', shell=True, cwd=tmpdirname, stdout = sys.stdout, stderr= sys.stderr)

            # Push fake result data
            # See https://stackoverflow.com/a/44946732/1360263  
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                for file_name, data in [('1.txt', io.BytesIO(b'1'*10000000)), ('2.txt', io.BytesIO(b'222'))]:
                    zip_file.writestr(file_name, data.getvalue())
            fs = gridfs.GridFS(db)
            result_id = fs.put(zip_buffer.getvalue(), filename='result.zip', mimetype ='application/zip')

            queue.update_one({'_id': job['_id']}, {'$set': {'status': 'done', 'result_id': result_id}})

            print(queue.find_one({'_id': job['_id']}))

except KeyboardInterrupt:
    print('Stopping...')
