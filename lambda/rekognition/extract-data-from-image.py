import boto3
import os
import uuid
import urllib
import time
import re
import io
from PIL import Image, ImageDraw
from collections import defaultdict

print('Loading function')

dynamodb = boto3.resource('dynamodb')
s3 = boto3.resource('s3')
rekognition = boto3.client('rekognition')
comprehend = boto3.client('comprehend')
comprehend_med = boto3.client('comprehendmedical')

table_name = os.environ['DYNAMODB_TABLE']

# From http://emailregex.com
email_regex = re.compile(r"""(?:[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*|"(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21\x23-\x5b\x5d-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])*")@(?:(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?|\[(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[a-z0-9-]*[a-z0-9]:(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21-\x5a\x53-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])+)\])""")


# --------------- Helper Functions ------------------

def get_image(bucket, key):
    file_stream = s3.Bucket(bucket).Object(key).get()['Body']
    return Image.open(file_stream)


def image_binary(image):
    stream = io.BytesIO()
    image.save(stream, format="JPEG")
    return stream.getvalue()


def clean_image(image):
    # Detect labels
    response = rekognition.detect_labels(Image={'Bytes': image_binary(image)}, MaxLabels=10)

    # Remove unsupported labels
    whitelist = ['Text', 'Paper']
    image_width = image.size[0]
    image_height = image.size[1]

    for label in response['Labels']:
        # Skip label if in whitelist
        if label['Name'] in whitelist:
            continue

        # print ("Label: " + label['Name'])
        # print ("Confidence: " + str(label['Confidence']))
        # print ("Instances:")
        for instance in label['Instances']:
            box = instance['BoundingBox']
            x = int(box['Left'] * image_width) * 0.9
            y = int(box['Top'] * image_height) * 0.9
            width = int(box['Left'] * image_width + box['Width'] * image_width) * 1.10
            height = int(box['Top'] * image_height + box['Height'] * image_height) * 1.10
            draw = ImageDraw.Draw(image)
            draw.rectangle(((x, y), (width, height)), fill='white')

    return image


def extract_text(image):
    lines = []
    response = rekognition.detect_text(Image={'Bytes': image_binary(image)})

    for detection in response['TextDetections']:
        if detection['Type'] == 'LINE':
            lines.append(detection['DetectedText'])

    return ', '.join(lines)


def extract_info(contact_string: str):
    contact_info = defaultdict(list)

    # Search email
    search_email = email_regex.search(contact_string.lower())

    if search_email:
        email = search_email.group(0)
        contact_info['CustomEmail'].append(email)

    # Extract info with comprehend
    response = comprehend.detect_entities(
        Text=contact_string,
        LanguageCode='en'
    )

    # print('Detect Entities (1):' + json.dumps(response, indent=2))

    for entity in response['Entities']:
        if entity['Type'] == 'PERSON':
            contact_info['Person'].append(entity['Text'])
        elif entity['Type'] == 'ORGANIZATION':
            contact_info['Organization'].append(entity['Text'])

    # Extract info with comprehend medical
    response = comprehend_med.detect_phi(
        Text=contact_string
    )

    # print('Detect Entities (2):' + json.dumps(response, indent=2))

    for entity in response['Entities']:
        if entity['Type'] == 'NAME':
            contact_info['Name'].append(entity['Text'])
        if entity['Type'] == 'EMAIL':
            contact_info['Email'].append(entity['Text'])
        elif entity['Type'] == 'PHONE_OR_FAX':
            contact_info['Phone'].append(entity['Text'])
        elif entity['Type'] == 'PROFESSION':
            contact_info['Title'].append(entity['Text'])
        elif entity['Type'] == 'ADDRESS':
            contact_info['Address'].append(entity['Text'])

    return dict(contact_info)


def save_image_metadata(bucket, key, metadata):
    object = s3.Object(bucket, key)
    object.metadata.update(metadata)
    object.copy_from(CopySource={'Bucket': bucket, 'Key': key},
                     Metadata=object.metadata, MetadataDirective='REPLACE')


def save_contact(contact_info):
    contact_info['ItemId'] = str(uuid.uuid1())
    contact_info['CreatedAt'] = int(time.time())

    table = dynamodb.Table(table_name)
    table.put_item(Item=contact_info)

    return contact_info['ContactId']


# --------------- Main handler ------------------


def lambda_handler(event, context):

    # Get the object from the event
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'])
    region = event['Records'][0]['awsRegion']

    try:
        # Download image from Amazon S3
        image = get_image(bucket, key)

        # Clean image
        image = clean_image(image)

        # Calls Amazon Rekognition DetectText API to detect text in S3 object
        text = extract_text(image)
        print('Extract Text: ', text)

        # Calls Amazon Comprehend API to detect text entities
        contact_info = extract_info(text)

        # Fill contact info and save it
        contact_info['Text'] = text
        contact_info['ImageUrl'] = 'http://{}.s3-{}.amazonaws.com/{}'.format(bucket, region, key)
        contact_id = save_contact(contact_info)

        response = {'ContactId': contact_id}

        save_image_metadata(bucket, key, response)

        # Print response to console.
        print(response)

        return response
    except Exception as e:
        print(e)
        print('Error processing {} from bucket {}.'.format(key, bucket))
        raise e
