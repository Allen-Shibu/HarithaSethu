# 🌿 HarithaSethu

> **Watching Every Change. Protecting Every Panchayat.**

HarithaSethu is an environmental intelligence platform that helps Gram Panchayats monitor environmental changes using satellite imagery and geospatial analytics. By comparing Sentinel-2 satellite images over time, the platform identifies meaningful environmental changes and presents them through an interactive dashboard, enabling Panchayat officials to make faster, data-driven decisions.

---

## 🚀 The Problem

Panchayats are responsible for protecting forests, water bodies, and public land, but monitoring these resources is still largely manual.

Current challenges include:
- 🌳 Vegetation loss goes unnoticed.
- 💧 Water bodies shrink before action is taken.
- 🏗️ Land-use changes are discovered only after they occur.
- 👥 Officials rely on citizen complaints and field inspections.

There is no continuous monitoring system to provide timely environmental insights.

---

## 💡 Our Solution

HarithaSethu continuously monitors the Panchayat using Sentinel-2 satellite imagery.

The platform automatically:
- Compares satellite imagery over time.
- Detects environmental changes.
- Highlights affected locations on an interactive map.
- Generates easy-to-understand environmental reports.

Instead of inspecting the entire Panchayat, officials can focus only on locations where significant changes have been detected.

---

## ✨ Features

- 🛰️ Monthly satellite image comparison
- 🌳 Green cover monitoring
- 💧 Water body monitoring
- 🏗️ Built-up area expansion detection
- 🗺️ Interactive GIS dashboard
- 📊 Environmental analytics
- 🤖 AI-generated environmental summaries
- 📈 Historical comparison

---

## ⚙️ How It Works

```
Panchayat Boundary (GeoJSON)
            │
            ▼
Google Earth Engine
            │
            ▼
Sentinel-2 Satellite Images
            │
            ▼
Cloud Filtering
            │
            ▼
Monthly Composite
            │
            ▼
Environmental Analysis
(NDVI • NDWI • Built-up)
            │
            ▼
Change Detection
            │
            ▼
Interactive Dashboard
            │
            ▼
Environmental Report
```

---

## 🛠️ Tech Stack

### Frontend
- React
- Vite
- TypeScript
- Tailwind CSS
- Leaflet
- Chart.js

### Backend
- FastAPI
- Python

### Geospatial
- Google Earth Engine
- Sentinel-2
- OpenStreetMap

### AI
- Google Gemini API

---

## 📊 Current Capabilities

- Compare satellite imagery across multiple months
- Detect vegetation changes
- Monitor water body variations
- Identify built-up area expansion
- Display environmental changes on an interactive dashboard
- Generate AI-powered environmental summaries

---

## 🏛️ Use Cases

- Gram Panchayats
- Local Self Government Institutions
- Environmental Monitoring
- Land-use Change Detection
- Water Resource Monitoring
- Sustainable Planning

---

## 🔮 Future Scope

- 🌳 Digital Tree Registry
- 📱 Citizen Geo-tagged Reporting
- 🦌 Wildlife Conflict Monitoring
- 🚨 Environmental Early Warning System
- 📊 Ward-wise Environmental Score
- 🤖 Predictive Environmental Analytics
- 📲 Mobile Application
- 🌍 Multi-Panchayat Support

---

## 📂 Project Structure

```
HarithaSethu/
│
├── frontend/
├── backend/
├── earth_engine/
├── geojson/
├── services/
├── components/
├── api/
├── assets/
└── docs/
```

---

## 🚀 Getting Started

### Clone the repository

```bash
git clone https://github.com/<your-username>/HarithaSethu.git
```

### Install Frontend

```bash
cd frontend
npm install
npm run dev
```

### Install Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

---

## 🌍 Built For

**Chakkittapara Grama Panchayat, Kerala**

Designed as a scalable platform that can support Gram Panchayats across Kerala.

---

## 📸 Demo

- Interactive GIS Dashboard
- Monthly Satellite Comparison
- Environmental Change Detection
- AI-generated Reports

> *(Add screenshots and deployment link here.)*

---

## 👥 Team

Developed as part of **Solve4Public**.

---

## 📄 License

This project is intended for educational, research, and public innovation purposes.

---

# 🌱 HarithaSethu

### *Watching Every Change. Protecting Every Panchayat.*

> **"HarithaSethu doesn't replace field inspections. It simply tells Panchayats where their attention is needed most. Because better decisions begin with better awareness."**
