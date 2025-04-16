import streamlit as st
import requests
import firebase_admin
from firebase_admin import credentials, storage, firestore
import io
from sklearn.base import BaseEstimator, TransformerMixin
import pandas as pd
import numpy as np
from tqdm import tqdm
from sklearn.model_selection import GridSearchCV
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
import h5py
from io import BytesIO
from PIL import Image
import io



# with open('src/model2.pkl', 'rb') as file:
        # model = joblib.load(file)

API_URL = "http://localhost:8000/"

@st.cache_data
def initialize_firebase():

    if not firebase_admin._apps:
        cred = credentials.Certificate("src/serviceAccountKey.json")  # Replace with your Firebase service account key
        firebase_admin.initialize_app(
            cred, 
            {"storageBucket": "skin-cancer-detection-c0570.firebasestorage.app"}  # Replace with your bucket name
        )

# Initialize firebase
initialize_firebase()

db = firestore.client()
bucket = storage.bucket()

# App title
st.title("Skin Cancer Detection")

# Description
st.header("Please upload your photo of the skin deformation!")

# File uploader
uploaded_file = st.file_uploader("Choose photo to upload", type=["jpg", "jpeg", "png"], accept_multiple_files=False)
print(uploaded_file)

# Display and upload photos
if uploaded_file is not None:
    # Store in session state
    st.session_state['uploaded_file'] = uploaded_file
    # st.write(f"File name: {uploaded_file.name}")

    image = Image.open(io.BytesIO(uploaded_file.read()))
    # image = image.resize((64,64))
    st.image(image, caption="Uploaded Image", use_container_width=False)
    response = requests.post(API_URL + "predict", data=uploaded_file.getvalue())
    
    # the interpretation of the result
    st.header("The result")
    if response.status_code == 200:
        prediction = response.json()["prediction"]
        st.success(f"Prediction: {prediction}")
    else:
        st.error(f"Error: {response.text}")

    


    # st.write(model.predict_proba(uploaded_file))
    # st.image(image, caption="Uploaded Image", use_container_width=True)
    # Upload to Firebase
    if st.button("Upload to Firebase"):
        try:
            # Upload file to Firebase Storage
            bucket = storage.bucket()
            blob = bucket.blob(f"images/{file_name}")
            blob.upload_from_file(uploaded_file, content_type='image/jpeg')

            # Save metadata to Firestore
            doc_ref = db.collection("images").document(file_id)
            doc_ref.set({
                "file_id": file_id,
                "user_name": user_name,
                "upload_time": upload_time.strftime("%Y-%m-%d %H:%M:%S"),
                "result": result,
            })

            st.success("Photo uploaded successfully!")
            st.write(f"File ID: {file_id}")
            st.write(f"Download URL: {blob.public_url}")
        except Exception as e:
            st.error(f"An error occurred: {e}")





