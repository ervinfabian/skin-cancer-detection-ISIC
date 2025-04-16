from typing import Union
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import JSONResponse
import joblib
import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel

#initializing a FastAPI instance
app = FastAPI()

#loading the trained machine learning model
with open('src/model2.pkl', 'rb') as file:
        model = joblib.load(file)

#preprocessing of the image
def image_preprocessing(image_bytes):
    images = []
    image = cv2.imdecode(np.fromstring(image_bytes, np.uint8), 1)
    image = cv2.resize(image, (64, 64))
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    images.append(image)
    X_ = np.array(images)
    X_test = X_.reshape(X_.shape[0], -1)
    return X_test

#the post request returning the result
@app.post("/predict")
async def predict(request: Request):
    try:
        data: bytes = await request.body()
        image_array = image_preprocessing(data)
        prediction = model.predict(image_array)
        return JSONResponse(content={"prediction": prediction.tolist()})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error occured: {e}")



