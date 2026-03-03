import os
import math
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtWidgets import (QAction, QDialog, QVBoxLayout, QDoubleSpinBox, 
                               QSpinBox, QLabel, QPushButton, QComboBox, 
                               QMessageBox, QGridLayout)
from qgis.core import (QgsProject, QgsVectorLayer, QgsField, QgsFields, QgsFeature, 
                       QgsGeometry, QgsPointXY, QgsWkbTypes, QgsDistanceArea, 
                       QgsUnitTypes, QgsVectorFileWriter)
from qgis.PyQt.QtGui import QIcon
import processing
import numpy as np

class SeismotectonicPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.action = QAction(QIcon(icon_path), "GeoAI: Fault Spine Extractor", self.iface.mainWindow())
        self.action.triggered.connect(self.run_dialog)

    def initGui(self):
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&GeoAI Seismology", self.action)

    def unload(self):
        self.iface.removePluginMenu("&GeoAI Seismology", self.action)
        self.iface.removeToolBarIcon(self.action)

    def run_dialog(self):
        self.dlg = QDialog()
        self.dlg.setWindowTitle("GeoAI Fault Spine Extractor v1.1")
        self.dlg.setMinimumWidth(500)
        layout = QGridLayout()

        # 1. Layer & Field Selection UI
        layout.addWidget(QLabel("Earthquake Point Layer:"), 0, 0)
        self.layer_combo = QComboBox()
        point_layers = [l for l in QgsProject.instance().mapLayers().values() 
                        if isinstance(l, QgsVectorLayer) and l.geometryType() == QgsWkbTypes.PointGeometry]
        for layer in point_layers: self.layer_combo.addItem(layer.name(), layer.id())
        self.layer_combo.currentIndexChanged.connect(self.update_fields)
        layout.addWidget(self.layer_combo, 0, 1)

        layout.addWidget(QLabel("Magnitude Field:"), 1, 0)
        self.mag_field_combo = QComboBox(); layout.addWidget(self.mag_field_combo, 1, 1)
        layout.addWidget(QLabel("Latitude Field (Y):"), 2, 0)
        self.lat_field_combo = QComboBox(); layout.addWidget(self.lat_field_combo, 2, 1)
        layout.addWidget(QLabel("Longitude Field (X):"), 3, 0)
        self.lon_field_combo = QComboBox(); layout.addWidget(self.lon_field_combo, 3, 1)

        # 2. Seismological Parameters (v1 Precision & Steps)
        layout.addWidget(QLabel("Min Magnitude (Mw):"), 4, 0)
        self.mag_spin = QDoubleSpinBox(); self.mag_spin.setDecimals(1); self.mag_spin.setSingleStep(0.1); self.mag_spin.setValue(0.0)
        layout.addWidget(self.mag_spin, 4, 1)

        self.unit_info_label = QLabel("Layer Unit: Detecting...")
        self.unit_info_label.setStyleSheet("color: #2c3e50; font-style: italic; font-weight: bold;")
        layout.addWidget(self.unit_info_label, 5, 0, 1, 2)

        layout.addWidget(QLabel("Clustering Dist (EPS):"), 6, 0)
        self.eps_spin = QDoubleSpinBox(); self.eps_spin.setSingleStep(0.001); layout.addWidget(self.eps_spin, 6, 1)

        layout.addWidget(QLabel("Min Samples (EQs):"), 7, 0)
        self.min_samples_spin = QSpinBox(); self.min_samples_spin.setRange(1, 5000); self.min_samples_spin.setValue(15)
        layout.addWidget(self.min_samples_spin, 7, 1)

        # Smoothing (Sigma) - Strategy v1.1: Range 0.001 to 20.0
        layout.addWidget(QLabel("Smoothing (Sigma):"), 8, 0)
        self.sigma_spin = QDoubleSpinBox()
        self.sigma_spin.setDecimals(3)
        self.sigma_spin.setRange(0.001, 20.0) 
        self.sigma_spin.setSingleStep(0.05)   
        self.sigma_spin.setValue(0.200)      
        layout.addWidget(self.sigma_spin, 8, 1)

        self.btn = QPushButton("Extract Spines & Save to Disk")
        self.btn.setStyleSheet("background-color: #1e8449; color: white; font-weight: bold; padding: 12px;")
        self.btn.clicked.connect(self.process)
        layout.addWidget(self.btn, 9, 0, 1, 2)

        self.dlg.setLayout(layout)
        self.update_fields(); self.dlg.show()

    def update_fields(self):
        """Automatically detects relevant fields and sets appropriate EPS steps/decimals."""
        self.mag_field_combo.clear(); self.lat_field_combo.clear(); self.lon_field_combo.clear()
        layer_id = self.layer_combo.currentData()
        if not layer_id: return
        layer = QgsProject.instance().mapLayer(layer_id)
        if not layer: return

        units = layer.crs().mapUnits()
        if units == QgsUnitTypes.DistanceDegrees:
            self.unit_info_label.setText("Unit: Degrees | Suggest EPS: 0.008-0.015")
            self.eps_spin.setDecimals(4); self.eps_spin.setSingleStep(0.0001); self.eps_spin.setValue(0.008)
        else:
            self.unit_info_label.setText("Unit: Meters | Suggest EPS: 500-2000")
            self.eps_spin.setDecimals(1); self.eps_spin.setSingleStep(10.0); self.eps_spin.setValue(1000.0)

        fields = [f.name() for f in layer.fields()]
        self.mag_field_combo.addItems(fields); self.lat_field_combo.addItems(fields); self.lon_field_combo.addItems(fields)

        # Intelligent field mapping for common seismology catalogs
        for f in fields:
            low_f = f.lower()
            if 'mw' in low_f or 'mag' in low_f: self.mag_field_combo.setCurrentText(f)
            if 'lat' in low_f or 'enlem' in low_f or low_f == 'y': self.lat_field_combo.setCurrentText(f)
            if ('lon' in low_f or 'boylam' in low_f or low_f == 'x') and 'type' not in low_f: self.lon_field_combo.setCurrentText(f)

    def calculate_strike(self, vector):
        """Calculates the strike angle from the principal component vector."""
        angle = math.degrees(math.atan2(vector[0], vector[1]))
        return round((angle + 360) % 180, 2)

    def process(self):
        """Main processing logic: Clustering, PCA extraction, and disk export."""
        try:
            # Dynamic Output Handling based on Project Location
            project_path = QgsProject.instance().fileName()
            base_dir = os.path.dirname(project_path) if project_path else os.path.join(os.path.expanduser("~"), "Documents")
            output_folder = os.path.join(base_dir, "GeoAI_Outputs")
            if not os.path.exists(output_folder): os.makedirs(output_folder)

            mag_limit = float(self.mag_spin.value())
            eps_val = float(self.eps_spin.value())
            min_pts = int(self.min_samples_spin.value())
            sigma_val = float(self.sigma_spin.value())
            
            # Formatted Title for Layer and File (v1 Standard)
            layer_title = "Spines_M{:.1f}_EPS{:.4f}_S{:.3f}_MS{:d}".format(mag_limit, eps_val, sigma_val, min_pts)
            gpkg_path = os.path.join(output_folder, f"{layer_title}.gpkg")

            layer_id = self.layer_combo.currentData()
            input_layer = QgsProject.instance().mapLayer(layer_id)
            if not input_layer: return
            mag_field = self.mag_field_combo.currentText()
            
            d = QgsDistanceArea()
            d.setSourceCrs(input_layer.crs(), QgsProject.instance().transformContext())
            d.setEllipsoid(QgsProject.instance().ellipsoid())

            # Data Preparation using QGIS Processing algorithms
            extent = self.iface.mapCanvas().extent()
            cropped = processing.run("native:extractbyextent", {'INPUT': input_layer, 'EXTENT': extent, 'OUTPUT': 'memory:'})['OUTPUT']
            filtered = processing.run("native:extractbyexpression", {'INPUT': cropped, 'EXPRESSION': f"\"{mag_field}\" >= {mag_limit}", 'OUTPUT': 'memory:'})['OUTPUT']
            dbscan = processing.run("native:dbscanclustering", {'INPUT': filtered, 'EPS': eps_val, 'MIN_CLUSTER_SIZE': min_pts, 'DBSCAN_HANDLE_NOISE': True, 'OUTPUT': 'memory:'})['OUTPUT']

            # Define Schema for the output Spine layer
            temp_layer = QgsVectorLayer(f"LineString?crs={input_layer.crs().authid()}", layer_title, "memory")
            prov = temp_layer.dataProvider()
            fields = QgsFields()
            for name, dtype in [("ClusterID", QVariant.Int), ("EQ_Count", QVariant.Int), ("Avg_Mw", QVariant.Double), ("Strike_Deg", QVariant.Double), ("Length_Km", QVariant.Double)]:
                fields.append(QgsField(name, dtype))
            prov.addAttributes(fields); temp_layer.updateFields()

            # Grouping clustered points for PCA analysis
            clusters_pts = {}; clusters_mags = {}
            for f in dbscan.getFeatures():
                cid = f['CLUSTER_ID']
                if cid is None or cid < 0: continue
                if cid not in clusters_pts: clusters_pts[cid] = []; clusters_mags[cid] = []
                p = f.geometry().asPoint(); clusters_pts[cid].append([p.x(), p.y()]); clusters_mags[cid].append(f[mag_field])

            total_clusters = len(clusters_pts) 
            created_count = 0 
            
            # Principal Component Analysis and Spine Smoothing per Cluster
            for cid, pts_list in clusters_pts.items():
                pts = np.array(pts_list)
                if len(pts) < min_pts: continue
                avg_mw = round(float(np.mean(clusters_mags[cid])), 2)
                
                # PCA to find the fault orientation
                center = pts.mean(axis=0); cov = np.cov(pts.T)
                vals, vecs = np.linalg.eig(cov); idx = np.argmax(vals)
                main_vec = vecs[:, idx]; strike_val = self.calculate_strike(main_vec)
                
                mag_dist = np.sqrt(vals[idx]) * 2.5
                raw_points = []
                for s in np.linspace(-mag_dist, mag_dist, 20):
                    anchor_p = center + main_vec * s
                    dists = np.linalg.norm(pts - anchor_p, axis=1)
                    local_pts = pts[dists < (eps_val * 1.5)]
                    # Adaptive weighted smoothing
                    raw_points.append(anchor_p * 0.2 + (local_pts.mean(axis=0) if len(local_pts) > 2 else anchor_p) * 0.8)

                if len(raw_points) > 5:
                    # Apply Gaussian-style smoothing on final spine points
                    smoothed = [QgsPointXY(float(p[0]), float(p[1])) for p in [np.mean(raw_points[max(0, i-2):min(len(raw_points), i+3)], axis=0) for i in range(len(raw_points))]]
                    geom = QgsGeometry.fromPolylineXY(smoothed)
                    feat = QgsFeature(temp_layer.fields()); feat.setGeometry(geom)
                    feat.setAttributes([cid, len(pts), avg_mw, strike_val, round(d.measureLength(geom)/1000, 2)])
                    prov.addFeatures([feat]); created_count += 1 

            # Permanent Storage: Write memory layer to GeoPackage on disk
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            QgsVectorFileWriter.writeAsVectorFormatV3(temp_layer, gpkg_path, QgsProject.instance().transformContext(), options)
            
            # Load the saved GeoPackage back into the QGIS project
            QgsProject.instance().addMapLayer(QgsVectorLayer(gpkg_path, layer_title, "ogr"))
            
            # Final Summary Notification (v1 Standard)
            QMessageBox.information(None, "Analysis Completed", 
                f"Total Clusters Found: {total_clusters}\n"
                f"Fault Spines Extracted: {created_count}\n\n"
                f"Output saved to: {gpkg_path}")

        except Exception as e:
            QMessageBox.critical(None, "Error", f"An unexpected error occurred: {str(e)}")