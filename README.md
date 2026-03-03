# GeoAI: Fault Spine Extractor (v1.1)
This QGIS plugin automates the structural interpretation of earthquake catalogs by transforming raw point seismicity data into linear fault spines using DBSCAN clustering and Principal Component Analysis (PCA).

🚀 New in Version 1.1 (Production Ready)
The latest update focuses on stability for large-scale seismic catalogs and improved workflow automation:

Memory Optimization (Disk-Safe): Solved RAM-related crashes by implementing a GeoPackage-based disk-write system. Every analysis is now permanently stored during processing.

Automatic Catalog Mapping: Enhanced intelligent field detection for Mw, Latitude, and Longitude. It now supports various international formats while strictly excluding irrelevant fields like 'type'.

Refined Seismotectonic Control: Optimized Sigma Smoothing range (0.001 - 20.0) to better capture both micro-seismicity details and regional structural trends.

Automated Project Archiving: Automatically creates a GeoAI_Outputs directory within your project path to keep your seismic research organized.

🛠 Features
Seismic Analytics: Real-time calculation of Strike (degrees) and Segment Length (km).

Intelligent Unit Detection: Automatically adjusts clustering parameters (EPS) based on the Layer's CRS (Degrees vs. Meters).

Adaptive Smoothing: Precise control over fault geometry via Gaussian-weighted smoothing.

🎓 About the Developer
Developed by Murat BEYHAN, a Geophysical Engineer (M.Sc.) and Seismologist.

Master's Degree: Ankara University, Türkiye (Geophysical Engineering).

Graduate Diploma: IISEE / Building Research Institute (BRI), Tsukuba, Japan (Seismology Course).