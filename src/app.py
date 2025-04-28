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
import tempfile


# URL of the API of the classification model
API_URL = "http://localhost:8000/"

# Connecting to the database
@st.cache_data
def initialize_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate("src/serviceAccountKey.json")  
        firebase_admin.initialize_app(
            cred, 
            {"storageBucket": "skin-cancer-detection-c0570.firebasestorage.app"}  
        )

# Initialize firebase
initialize_firebase()

# connecting to the firestore for image storage
db = firestore.client()
bucket = storage.bucket()

# App title
st.title("Skin Cancer Detection")

st.header("We need a few information for better precision")

# Obligatory parameters
age_of_pacient = st.number_input("Please give us your age")
sex = st.selectbox("Please give us your sex", ("Male", "Female"))
diameter_of_lesion_in_mm = st.number_input("Please give us a the approximate diameter of the lesion in mm")

# Description
st.header("Please upload your photo of the skin deformation!")

# File uploader
uploaded_file = st.file_uploader("Choose photo to upload", type=["jpg", "jpeg", "png"], accept_multiple_files=False)

# Display and upload photos
if uploaded_file is not None and age_of_pacient != 0 and diameter_of_lesion_in_mm != 0:
    # Store in session state
    st.session_state['uploaded_file'] = uploaded_file

    # processing the image for API communication
    image = Image.open(io.BytesIO(uploaded_file.read()))
    st.image(image, caption="Uploaded Image", use_container_width=False)

    # Requesting classification of the image through API
    response = requests.post(API_URL + "predict", data=uploaded_file.getvalue())
    
    # the interpretation of the result
    st.header("The result")
    if response.status_code == 200:
        prediction = response.json()["prediction"]
        if prediction[0] == 0:
            st.success("NOT necessary for you you to contact a professional regarding the skin lesion")
        else:
            st.succes("We suggest you to contact a professional regarding your skin lesion as soon as possible")
    else:
        st.error(f"Error: {response.text}")


    st.header("If you agree to our use of the image you uploaded, you can upload it to our database")
    if st.button("Upload to Database"):
        try:
            # Upload image to Firebase Storage

            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(uploaded_file.getvalue())
                temp_file_path = temp_file.name

            # Upload to Firebase
            blob = bucket.blob(f'uploads/{uploaded_file.name}')
            blob.upload_from_filename(temp_file_path)

            st.success("Photo uploaded successfully!")
            # st.write(f"File ID: {file_id}")
            # st.write(f"Download URL: {blob.public_url}")
        except Exception as e:
            st.error(f"An error occurred: {e}")





