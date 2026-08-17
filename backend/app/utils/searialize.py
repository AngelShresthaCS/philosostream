def serialize_mongo_doc(doc):
    doc["_id"] = str(doc["_id"])
    # Convert datetime objects to strings if you have them!
    return doc