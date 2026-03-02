import os
import math
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtWidgets import (QAction, QDialog, QVBoxLayout, QDoubleSpinBox, 
                               QSpinBox, QLabel, QPushButton, QComboBox, 
                               QMessageBox, QGridLayout)
from qgis.core import (QgsProject, QgsVectorLayer, QgsField, QgsFields, QgsFeature, 
                       QgsGeometry, QgsPointXY, QgsWkbTypes, QgsDistanceArea, QgsUnitTypes)
from qgis.PyQt.QtGui import QIcon
import processing
import numpy as np

class SeismotectonicPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.action = QAction(
            QIcon(icon_path), 
            "GeoAI: Fault Spine Extractor", 
            self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run_dialog)

    def initGui(self):
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&GeoAI Seismology", self.action)

    def unload(self):
        self.iface.removePluginMenu("&GeoAI Seismology", self.action)
        self.iface.removeToolBarIcon(self.action)

    def run_dialog(self):
        self.dlg = QDialog()
        self.dlg.setWindowTitle("GeoAI Fault Spine Extractor v1.0")
        self.dlg.setMinimumWidth(500)
        layout = QGridLayout()

        # 1. Layer Selection
        layout.addWidget(QLabel("Earthquake Point Layer:"), 0, 0)
        self.layer_combo = QComboBox()
        point_layers = [l for l in QgsProject.instance().mapLayers().values() 
                        if isinstance(l, QgsVectorLayer) and l.geometryType() == QgsWkbTypes.PointGeometry]
        for layer in point_layers: self.layer_combo.addItem(layer.name(), layer.id())
        self.layer_combo.currentIndexChanged.connect(self.update_fields)
        layout.addWidget(self.layer_combo, 0, 1)

        # 2. Attribute Field Selection
        layout.addWidget(QLabel("Magnitude Field:"), 1, 0)
        self.mag_field_combo = QComboBox(); layout.addWidget(self.mag_field_combo, 1, 1)

        layout.addWidget(QLabel("Latitude Field (Y):"), 2, 0)
        self.lat_field_combo = QComboBox()
        layout.addWidget(self.lat_field_combo, 2, 1)

        layout.addWidget(QLabel("Longitude Field (X):"), 3, 0)
        self.lon_field_combo = QComboBox()
        layout.addWidget(self.lon_field_combo, 3, 1)

        # 3. Processing Parameters
        layout.addWidget(QLabel("Min Magnitude (Mw):"), 4, 0)
        self.mag_spin = QDoubleSpinBox(); self.mag_spin.setDecimals(1); self.mag_spin.setSingleStep(0.1); self.mag_spin.setValue(0.0)
        layout.addWidget(self.mag_spin, 4, 1)

        # Dynamic Unit Information Label
        self.unit_info_label = QLabel("Layer Unit: Detecting...")
        self.unit_info_label.setStyleSheet("color: #2c3e50; font-style: italic; font-weight: bold;")
        layout.addWidget(self.unit_info_label, 5, 0, 1, 2)

        layout.addWidget(QLabel("Clustering Dist (EPS):"), 6, 0)
        self.eps_spin = QDoubleSpinBox(); self.eps_spin.setDecimals(6); self.eps_spin.setRange(0.000001, 100000.0)
        layout.addWidget(self.eps_spin, 6, 1)

        layout.addWidget(QLabel("Min Samples (EQs):"), 7, 0)
        self.min_samples_spin = QSpinBox(); self.min_samples_spin.setRange(1, 5000); self.min_samples_spin.setValue(15)
        layout.addWidget(self.min_samples_spin, 7, 1)

        layout.addWidget(QLabel("Smoothing (Sigma):"), 8, 0)
        self.sigma_spin = QDoubleSpinBox(); self.sigma_spin.setDecimals(3); self.sigma_spin.setSingleStep(0.01); self.sigma_spin.setValue(0.2)
        layout.addWidget(self.sigma_spin, 8, 1)

        self.btn = QPushButton("Extract Spines with Analytics")
        self.btn.setStyleSheet("background-color: #1e8449; color: white; font-weight: bold; padding: 12px;")
        self.btn.clicked.connect(self.process)
        layout.addWidget(self.btn, 9, 0, 1, 2)

        self.dlg.setLayout(layout)
        self.update_fields(); self.dlg.show()

    def update_fields(self):
        self.mag_field_combo.clear()
        self.lat_field_combo.clear()
        self.lon_field_combo.clear()
        
        layer_id = self.layer_combo.currentData()
        if layer_id:
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer:
                units = layer.crs().mapUnits()
                if units == QgsUnitTypes.DistanceDegrees:
                    self.unit_info_label.setText("Unit: Degrees (WGS84) | Suggest EPS: 0.008-0.015")
                    self.eps_spin.setDecimals(4)
                    self.eps_spin.setSingleStep(0.0001)
                    self.eps_spin.setValue(0.008)
                else:
                    self.unit_info_label.setText("Unit: Meters/Metric | Suggest EPS: 500-2000")
                    self.eps_spin.setDecimals(1)
                    self.eps_spin.setSingleStep(100.0)
                    self.eps_spin.setValue(1000.0)

                fields = [f.name() for f in layer.fields()]
                self.mag_field_combo.addItems(fields)
                self.lat_field_combo.addItems(fields)
                self.lon_field_combo.addItems(fields)

                for f in fields:
                    f_lower = f.lower()
                    if f_lower in ['mag', 'magnitude', 'mw']: self.mag_field_combo.setCurrentText(f)
                    if f_lower in ['lat', 'latitude', 'enlem', 'y']: self.lat_field_combo.setCurrentText(f)
                    if f_lower in ['lon', 'longitude', 'boylam', 'x']: self.lon_field_combo.setCurrentText(f)

    def calculate_strike(self, vector):
        angle = math.degrees(math.atan2(vector[0], vector[1]))
        strike = (angle + 360) % 180 
        return round(strike, 2)

    def process(self):
        try:
            extent = self.iface.mapCanvas().extent()
            layer_id = self.layer_combo.currentData()
            input_layer = QgsProject.instance().mapLayer(layer_id)
            if not input_layer: return
            
            mag_field = self.mag_field_combo.currentText()
            mag_limit = float(self.mag_spin.value())
            eps_val = float(self.eps_spin.value())
            min_pts = int(self.min_samples_spin.value())
            sigma_val = float(self.sigma_spin.value())
            
            d = QgsDistanceArea()
            d.setSourceCrs(input_layer.crs(), QgsProject.instance().transformContext())
            d.setEllipsoid(QgsProject.instance().ellipsoid())

            cropped = processing.run("native:extractbyextent", {'INPUT': input_layer, 'EXTENT': extent, 'OUTPUT': 'memory:'})['OUTPUT']
            filtered = processing.run("native:extractbyexpression", {'INPUT': cropped, 'EXPRESSION': f"\"{mag_field}\" >= {mag_limit}", 'OUTPUT': 'memory:'})['OUTPUT']
            
            dbscan_params = {
                'INPUT': filtered,
                'EPS': eps_val,
                'MIN_CLUSTER_SIZE': min_pts,
                'DBSCAN_HANDLE_NOISE': True,
                'OUTPUT': 'memory:'
            }
            dbscan = processing.run("native:dbscanclustering", dbscan_params)['OUTPUT']

            # Updated Layer Title with high precision for Smoothing (S)
            layer_title = "Spines_M{:.1f}_EPS{:.4f}_S{:.3f}_MS{:03d}".format(mag_limit, eps_val, sigma_val, min_pts)
            output_layer = QgsVectorLayer(f"LineString?crs={input_layer.crs().authid()}", layer_title, "memory")
            prov = output_layer.dataProvider()
            
            fields = QgsFields()
            fields.append(QgsField("ClusterID", QVariant.Int))
            fields.append(QgsField("EQ_Count", QVariant.Int))
            fields.append(QgsField("Avg_Mw", QVariant.Double))
            fields.append(QgsField("Strike_Deg", QVariant.Double))
            fields.append(QgsField("Length_Km", QVariant.Double))
            prov.addAttributes(fields)
            output_layer.updateFields()

            clusters_pts = {}
            clusters_mags = {}
            for f in dbscan.getFeatures():
                cid = f['CLUSTER_ID']
                if cid is None or cid < 0: continue
                if cid not in clusters_pts:
                    clusters_pts[cid] = []
                    clusters_mags[cid] = []
                p = f.geometry().asPoint()
                clusters_pts[cid].append([p.x(), p.y()])
                clusters_mags[cid].append(f[mag_field])

            created_count = 0 
            for cid, pts_list in clusters_pts.items():
                pts = np.array(pts_list)
                if len(pts) < min_pts: continue
                
                avg_mw = round(float(np.mean(clusters_mags[cid])), 2)
                center = pts.mean(axis=0); cov = np.cov(pts.T)
                vals, vecs = np.linalg.eig(cov); idx = np.argmax(vals)
                main_vec = vecs[:, idx]
                strike_val = self.calculate_strike(main_vec)
                
                mag_dist = np.sqrt(vals[idx]) * 2.5
                raw_points = []
                for s in np.linspace(-mag_dist, mag_dist, 20):
                    anchor_p = center + main_vec * s
                    dists = np.linalg.norm(pts - anchor_p, axis=1)
                    local_pts = pts[dists < (eps_val * 1.5)]
                    if len(local_pts) > 2: 
                        raw_points.append(anchor_p * 0.2 + local_pts.mean(axis=0) * 0.8)
                    else: 
                        raw_points.append(anchor_p)

                if len(raw_points) > 5:
                    smoothed = []
                    for i in range(len(raw_points)):
                        avg_p = np.mean(raw_points[max(0, i-2):min(len(raw_points), i+3)], axis=0)
                        smoothed.append(QgsPointXY(float(avg_p[0]), float(avg_p[1])))
                    
                    geom = QgsGeometry.fromPolylineXY(smoothed)
                    length_km = round(d.measureLength(geom) / 1000, 2)
                    
                    feat = QgsFeature(output_layer.fields())
                    feat.setGeometry(geom)
                    feat.setAttributes([cid, len(pts), avg_mw, strike_val, length_km])
                    prov.addFeatures([feat])
                    created_count += 1 

            QgsProject.instance().addMapLayer(output_layer)
            QMessageBox.information(None, "Success", 
                f"Extraction Completed!\n\n"
                f"Total Clusters Found: {len(clusters_pts)}\n"
                f"Spines Created (After Filters): {created_count}\n\n"
                f"Layer '{layer_title}' added to map.")

        except Exception as e:
            QMessageBox.critical(None, "Error", f"Error: {str(e)}")