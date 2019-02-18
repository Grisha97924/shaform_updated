from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
import logging
import os
from pathlib import Path
from FastText import load_model
from legend import legend, important
import logging
import base64
import json
import re
import argparse
import io
import datetime
from google.cloud import pubsub_v1
from google.cloud import vision
from flask import Flask, request, render_template
from google.cloud import storage
import sys
import string
import pandas as pd
import textract
from werkzeug.utils import secure_filename

if sys.version_info[0] >= 3:
    unicode = str

vision_client = vision.ImageAnnotatorClient()
publisher = pubsub_v1.PublisherClient()
storage_client = storage.Client()

project_id = '791969113495'

with open('config.json') as f:
    data = f.read()
config = json.loads(data)

app = Flask(__name__)
app.config['UPLOAD_PATH'] = 'var/backups'

# Configure this environment variable via app.yaml
CLOUD_STORAGE_BUCKET = 'shaform2'
CLOUD_STORAGE_BUCKET2 = 'shaformpdf'

def explicit():
    from google.cloud import storage

    # Explicitly use service account credentials by specifying the private key
    # file.
    storage_client = storage.Client.from_service_account_json(
        'creds/sha2.json')

def detect_text(bucket, filename):
    print('Looking for text in image {}'.format(filename))

    futures = []
    
    text_detection_response = vision_client.text_detection({
        'source': {'image_uri': 'gs://{}/{}'.format(bucket, filename)}
    })
    annotations = text_detection_response.text_annotations
    if len(annotations) > 0:
        text = annotations[0].description
    else:
        text = ''
    print('Extracted text {} from image ({} chars).'.format(text, len(text)))

    src_lang = detect_language_response['language']
    print('Detected language {} for text {}.'.format(src_lang, text))


def validate_message(message, param):
    var = message.get(param)
    if not var:
        raise ValueError('{} is not provided. Make sure you have \
                          property {} in the request'.format(param, param))
    return var


def process_image(file, context):
    """Cloud Function triggered by Cloud Storage when a file is changed.
    Args:
        file (dict): Metadata of the changed file, provided by the triggering
                                 Cloud Storage event.
        context (google.cloud.functions.Context): Metadata of triggering event.
    Returns:
        None; the output is written to stdout and Stackdriver Logging
    """
    bucket = validate_message(file, 'bucket')
    name = validate_message(file, 'name')

    detect_text(bucket, name)

    print('File {} processed.'.format(file['name']))

    
def save_result(event, context):
    if event.get('data'):
        message_data = base64.b64decode(event['data']).decode('utf-8')
        message = json.loads(message_data)
    else:
        raise ValueError('Data sector is missing in the Pub/Sub message.')

    text = validate_message(message, 'text')
    filename = validate_message(message, 'filename')
    lang = validate_message(message, 'lang')

    print('Received request to save file {}.'.format(filename))

    bucket_name = config['RESULT_BUCKET']
    result_filename = '{}_{}.txt'.format(filename, lang)
    bucket = storage_client.get_bucket(bucket_name)
    blob = bucket.blob(result_filename)

    print('Saving result to {} in bucket {}.'.format(result_filename,
                                                     bucket_name))

    blob.upload_from_string(text)
    
    print(blob.public_url)

    print('File saved.')


def async_detect_document(bucket, filename):
    """OCR with PDF/TIFF as source files on GCS"""
    from google.cloud import vision
    from google.cloud import storage
    from google.protobuf import json_format
    # Supported mime_types are: 'application/pdf' and 'image/tiff'
    mime_type = 'application/pdf'

    # How many pages should be grouped into each json output file.
    batch_size = 100
     
    gcs_source_uri = 'gs://{}/{}'.format(bucket, filename)
    gcs_destination_uri = 'gs://{}/{}.json'.format(bucket, filename)
    

    client = vision.ImageAnnotatorClient()

    feature = vision.types.Feature(
        type=vision.enums.Feature.Type.DOCUMENT_TEXT_DETECTION)

    gcs_source = vision.types.GcsSource(uri=gcs_source_uri)
    input_config = vision.types.InputConfig(
        gcs_source=gcs_source, mime_type=mime_type)

    gcs_destination = vision.types.GcsDestination(uri=gcs_destination_uri)
    output_config = vision.types.OutputConfig(
        gcs_destination=gcs_destination, batch_size=batch_size)

    async_request = vision.types.AsyncAnnotateFileRequest(
        features=[feature], input_config=input_config,
        output_config=output_config)

    operation = client.async_batch_annotate_files(
        requests=[async_request])

    print('Waiting for the operation to finish.')
    operation.result(timeout=180)

    # Once the request has completed and the output has been
    # written to GCS, we can list all the output files.
    storage_client = storage.Client()

    match = re.match(r'gs://([^/]+)/(.+)', gcs_destination_uri)
    bucket_name = match.group(1)
    prefix = match.group(2)

    bucket = storage_client.get_bucket(bucket_name=bucket_name)

    # List objects with the given prefix.
    blob_list = list(bucket.list_blobs(prefix=prefix))
    print('Output files:')
    for blob in blob_list:
        print(blob.name)

    # Process the first output file from GCS.
    # Since we specified batch_size=2, the first response contains
    # the first two pages of the input file.
    output = blob_list[0]

    json_string = output.download_as_string()
    response = json_format.Parse(
        json_string, vision.types.AnnotateFileResponse())

    # The actual response for the first page of the input file.
    #print(len(response.responses))
    
    first_page_response = response.responses[0]
    annotation = first_page_response.full_text_annotation
    #print(annotation)
    
    c = ''
    
    for i in range(len(response.responses)):
        a = response.responses[i]
        b = a.full_text_annotation
        c = c + b.text + '\n'
        
    result_filename = filename + '.txt' #'{}_{}.txt'.format(filename, lang)
    #bucket = 'shaforms2' #storage_client.get_bucket(bucket_name)
    blob = bucket.blob(result_filename)

    print('Saving result to {} in bucket {}.'.format(result_filename,
                                                     bucket_name))

    blob.upload_from_string(c)

    print('File saved.')
    
    # Here we print the full text from the first page.
    # The response contains more information:
    # annotation/pages/blocks/paragraphs/words/symbols
    # including confidence scores and bounding boxes
    #print(u'Full text:\n{}'.format(
     #   annotation.text))


@app.route('/')
def index():
    return render_template('index2.html')

@app.route('/store_txt', methods=['GET'])
def store_txt():
    userKeyword = flask.request.args.get('userKeyword')

    save_path = 'var/backups/'

    currentDT = datetime.datetime.now()

    name_of_file = 'userKeyword-' + currentDT.strftime("%Y%m%d%H%M%S")

    completeName = os.path.join(save_path, name_of_file+".txt")         

    file1 = open(completeName, "w+")

    file1.write(userKeyword)

    file1.close()

    return 'success'

@app.route('/upload', methods=['POST'])
def upload():
    print ("How many files are selected ? ")
    
    f = request.files.getlist("files")
    print (f)
    #uploaded_file = request.files.get('file')

    if not f:
        return 'No file uploaded.', 400
    
      

    gcs = storage.Client()

    final2 = []
    title2 =[]
    length2 = []
    imp = []
    sublen = []

    for uploaded_file in f:
        
        abc = secure_filename(uploaded_file.filename)
        uploaded_file.save(os.path.join(app.config['UPLOAD_PATH'], abc))

        if uploaded_file.filename.lower().endswith('txt'):
      
            bucket = gcs.get_bucket(CLOUD_STORAGE_BUCKET)
            blob = bucket.blob(uploaded_file.filename)
            blob.upload_from_string(
                uploaded_file.read(),
                content_type=uploaded_file.content_type
            )
            data = blob.download_as_string()
            data = unicode(data, errors='ignore')
            data = data.split('\n')
            first15 = data[0:15]

            model2 = load_model('titles.bin')
            
            titles = model2.predict(first15)
            title = "title not found"
            for i in titles:
                for k in i:
                    if k[0] == "__label__1":
                        a = titles.index(i)
                        title = first15[a]
            title = title.lower()
            title = string.capwords(title)

            model = load_model('shaforms.bin')
            labels = model.predict(data)
            clauses = []
            for i in labels:
                for k in i:
                    if k[0] != '__label__222':
                        clauses.append(str(k))
                break

            final = []
            for i in clauses:
                z = i.rfind("'")
                code = i[11:z]
                final.append(legend[code])

            answer = ''
            for i in final:
                answer = answer + i + ", "
            a = len(answer)-2
            answer = answer[:a]
            '''
            link = blob.public_url + '_en.txt'
            yyy = str(link.replace('shaform2', 'shaform22', 1))
            '''
            length = len(final)
            final2.append(final)
            length2.append(length)
            title2.append(title)
            

            impClauses = []
            
            for i in important:
                if i in final and i not in impClauses:
                    impClauses.append(i)
            if len(impClauses) == 0:
                impClauses = ["None found"]
            tmplen = len(impClauses)
            imp.append(impClauses)
            sublen.append(tmplen)
        
        else:

            text = textract.process('var/backups/'+abc )
            #print(text)

            '''
            
            bucket = gcs.get_bucket(CLOUD_STORAGE_BUCKET2)
            blob = bucket.blob(uploaded_file.filename)
            blob.upload_from_string(
                uploaded_file.read(),
                content_type=uploaded_file.content_type
            )

            #text = textract.process(uploaded_file)
            #print(text)

            async_detect_document('shaformpdf', uploaded_file.filename)

            blob2 = bucket.blob(uploaded_file.filename+".txt")

            data = blob2.download_as_string()
            '''
            data = unicode(text, errors='ignore')
            
            data = data.split('\n')
            first15 = data[0:15]
            
            for i in range(len(first15)):
                first15[i] = first15[i].strip()
            print(first15)
            model = load_model('shaforms.bin')
            
            model2 = load_model('titles.bin')
            titles = model2.predict(first15)
            title = "title not found"
            for i in titles:
                for k in i:
                    if k[0] == "__label__1":
                        a = titles.index(i)
                        title = first15[a]
            title = title.lower()
            title = string.capwords(title)
            
            for i in range(len(data)):
                data[i] = data[i].strip()

            print(data)
            labels = model.predict(data)
            clauses = []
            for i in labels:
                for k in i:
                    if k[0] != '__label__222':
                        clauses.append(str(k))
                break
            
            final = []
            for i in clauses:
                z = i.rfind("'")
                code = i[11:z]
                final.append(legend[code])

            length = len(final)
            final2.append(final)
            length2.append(length)
            title2.append(title)

            impClauses = []
            
            for i in important:
                if i in final and i not in impClauses:
                    impClauses.append(i)
            if len(impClauses) == 0:
                impClauses = ["None found"]
            tmplen = len(impClauses)
            imp.append(impClauses)
            sublen.append(tmplen)
            #zzz = str("Download link: " + blob.public_url + '.txt')
            
        
    
    

    blocks = len(final2)

    show = range(0,blocks*5, 5)

    if blocks > 1:
        document = 'Documents'
    else:
        document = 'Document'
    
    print(blocks)
    print(document)
    
    columns = {"File name": title2}
    for k in important:
        col = {}
        row = []
        for i in range(len(final2)):
            if k in final2[i]:
                row.append("+")
            else:
                row.append("")
        col[k] = row
        columns.update(col)
        
    a = pd.DataFrame.from_dict(columns)

    a = a.to_html()
    a.replace('\n', '')
    #print(a)
    
    

    return render_template('page3.html',tables=a, final2=final2, title2=title2, length2=length2, blocks=blocks, document=document, imp=imp, sublen=sublen, show=show)

@app.errorhandler(500)
def server_error(e):
    logging.exception('An error occurred during a request.')
    return """
    An internal error occurred: <pre>{}</pre>
    See logs for full stacktrace.
    """.format(e), 500


if __name__ == '__main__':
    # This is used when running locally. Gunicorn is used to run the
    # application on Google App Engine. See entrypoint in app.yaml.
    app.run(host='127.0.0.1', port=8080, debug=True)
# [END gae_flex_storage_app]
