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


class SelectColumns(BaseEstimator, TransformerMixin):
    def __init__(self, columns):
        self.columns = columns
    def fit(self, X, y=None):
        return self
    def transform(self, X):
        return X[self.columns]

def open_model():
    
    with open('src/model.pkl', 'rb') as file:
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





# Loading of the model
open_model()

print("kivan a fasz")


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

    # Upload to Firebase
    if st.button("Upload to Firebase"):
        bucket = storage.bucket()
        blob = bucket.blob(f"images/{uploaded_file.name}")
        blob.upload_from_file(uploaded_file)
        st.success("Photo uploaded successfully!")


print("")
print("miafasz")



