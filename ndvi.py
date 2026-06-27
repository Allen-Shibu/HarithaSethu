import ee
import json

ee.Initialize(project="n8n-workflows-473615") 

# Load your GeoJSON
with open('Chakkittapara Grama Panchayat - Boundaries.geojson') as f:
    geojson = json.load(f)

# Define the boundary
coords = geojson['features'][0]['geometry']['coordinates']
panchayat = ee.Geometry.Polygon(coords)

# Pull Sentinel-2 imagery
image = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(panchayat)
    .filterDate('2024-01-01', '2024-12-31')
    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
    .median())

# Compute NDVI
ndvi = image.normalizedDifference(['B8', 'B4'])

# Compute NDWI
ndwi = image.normalizedDifference(['B3', 'B8'])

# Get mean values for the panchayat
result = ndvi.addBands(ndwi).reduceRegion(
    reducer=ee.Reducer.mean(),
    geometry=panchayat,
    scale=10
).getInfo()

print("NDVI:", result['nd'])
print("NDWI:", result['nd_1'])