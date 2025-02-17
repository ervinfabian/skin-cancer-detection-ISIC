import streamlit as st
from PIL import Image
import firebase_admin
from firebase_admin import credentials, storage, firestore
import io
import uuid
import joblib
import kaggle
import pickle
from sklearn.base import BaseEstimator, TransformerMixin
import datetime
import cv2
import pandas as pd
import numpy as np
import os
from tqdm import tqdm
from sklearn.model_selection import GridSearchCV
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
import h5py
from io import BytesIO



# class SelectColumns(BaseEstimator, TransformerMixin):
#     def __init__(self, columns):
#         self.columns = columns
#     def fit(self, X, y=None):
#         return self
#     def transform(self, X):
#         return X[self.columns]

with open('src/model2.pkl', 'rb') as file:
        model = joblib.load(file)


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
st.write("Please upload your photo of the skin deformation!")

# File uploader
uploaded_file = st.file_uploader("Choose photo to upload", type=["jpg", "jpeg", "png"], accept_multiple_files=False)

# Display and upload photos
if uploaded_file is not None:
    # Store in session state
    st.session_state['uploaded_file'] = uploaded_file
    st.write(f"File name: {uploaded_file.name}")

    file_id = str(uuid.uuid4())
    user_name = f"{file_id}.jpg"
    upload_time = datetime.datetime.now()
    result = "valami"

    # estimating
    images = []
    image = cv2.imdecode(np.fromstring(uploaded_file.read(), np.uint8), 1)
    image = cv2.resize(image, (64, 64))
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    images.append(image)
    X_ = np.array(images)
    X_test = X_.reshape(X_.shape[0], -1)
    st.write(model.predict(X_test))

    # st.write(model.predict_proba(uploaded_file))
    st.image(image, caption="Uploaded Image", use_container_width=True)
    st.write(model.predict_proba(image))
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





