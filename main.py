from fastapi import FastAPI

app = FastAPI()

@app.get("/hello/")
def say_hello():
    return {"message": "hello osama"}

# لو تريد أيضًا دعم POST:
@app.post("/hello/")
def say_hello_post():
    return {"message": "hello osama"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
