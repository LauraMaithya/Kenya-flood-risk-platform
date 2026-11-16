# Kenya-flood-risk-platform
# Kenya Flood Monitoring and Prediction Platform

## Project Overview

The Kenya Flood Monitoring and Prediction Platform is a web-based flood monitoring system that uses environmental data processing and a Random Forest machine learning classifier to assess and display flood risk across Kenyan counties.

The project aims to address the challenges of flood monitoring in Kenya, particularly the limited availability of localised environmental information, fragmented data sources and the need for accessible flood risk information.

The platform integrates historical environmental datasets, automated data acquisition, machine learning classification and an interactive web dashboard. It classifies flood risk into three categories: **Low, Medium and High**, allowing users to explore county-level risk information, examine historical records and view alerts associated with high-risk predictions.

The system combines NASA POWER environmental data, EM-DAT historical flood events and DAHITI water-level observations to develop and evaluate its prediction model. Its operational data pipeline also acquires delayed NASA POWER observations and current-day Open-Meteo data. Simulated IoT readings are maintained separately and are not used for production flood predictions.

## Project Objectives

The main objectives of the project are to:

1. Examine existing flood patterns, their impacts and the challenges faced by flood monitoring organisations in Kenya.
2. Analyse existing flood monitoring platforms and machine learning approaches to identify gaps.
3. Design and implement an automated Extract, Transform and Load (ETL) pipeline and a Random Forest classifier for flood risk classification.
4. Develop a web-based dashboard for displaying county-level flood risk classifications, historical data and alerts.
5. Test and evaluate the developed machine learning model and system functionality.

## Key Features

### 1. Flood Risk Prediction
- Uses a trained Random Forest classification model.
- Classifies environmental observations into Low, Medium and High flood risk categories.
- Uses seven selected predictors.
- Loads the saved model for prediction without retraining during application operation.

### 2. Interactive Kenya Flood Risk Dashboard
- Displays flood risk information through an interactive map of Kenya.
- Provides county-level risk visualisation.
- Includes county selection and date-based filtering.
- Displays key indicators and environmental information.
- Covers the 47 Kenyan counties on the map, with historical model predictor coverage available for 34 counties.

### 3. Historical Data Exploration
- Provides access to stored historical environmental observations and flood risk predictions.
- Allows users to filter records by county, date and risk category.
- Supports historical trend exploration.
- Provides CSV downloads for further analysis.

### 4. Alert Management
- Provides an alerts interface for monitoring high-risk predictions.
- Applies defined conditions to determine alert eligibility.
- Supports the reconciliation of eligible alerts while preventing duplicate notifications.
- Displays alerts within the application.

### 5. Automated Data Processing
- Acquires environmental data from external APIs.
- Cleans, validates and standardises incoming observations.
- Aligns observations by county and date.
- Prepares the required model predictors.
- Stores processed observations and predictions in PostgreSQL.

### 6. User Authentication and Administration
- Provides authenticated access to the application.
- Supports administrative management of users and system settings.
- Provides access to dashboard functionality according to user permissions.

## Data Sources

The project uses the following primary historical datasets:

| Data Source | Description | Purpose |
|---|---|---|
| NASA POWER | Environmental data, including precipitation, temperature, relative humidity and soil wetness. | Provides environmental predictors for flood risk classification. |
| EM-DAT | Historical flood disaster events, including event dates and locations. | Provides historical flood event evidence for constructing reference labels. |
| DAHITI | Water-level observations derived from satellite altimetry. | Provides supporting hydrological evidence for flood risk labelling. |

**Historical data period:** 2010–2025.

The operational data acquisition pipeline additionally uses:

- **NASA POWER API:** Acquires delayed environmental observations.
- **Open-Meteo API:** Acquires current-day weather observations for operational classification.
- **Simulated IoT telemetry:** Provides separately identified simulated sensor readings for testing and demonstrating the telemetry workflow.

Simulated IoT readings are not treated as actual physical sensor measurements and are excluded from production flood risk predictions. Physical IoT sensor hardware and field deployment were outside the scope of this implementation.

## System Architecture and Workflow

The platform follows an integrated data processing, machine learning and web application workflow.

1. **Data Acquisition:** Historical environmental and flood event data are obtained from NASA POWER, EM-DAT and DAHITI. Operational observations are also acquired through the supported APIs.
2. **Data Processing (ETL):** Data are cleaned, standardised, validated and aligned by county and date.
3. **Feature Engineering:** The required seven predictors are prepared according to the model's input requirements.
4. **Model Classification:** The trained Random Forest model processes eligible environmental observations and assigns Low, Medium or High flood risk classifications.
5. **Database Storage:** Environmental observations, predictions and alert records are stored in PostgreSQL.
6. **Dashboard Visualisation:** Processed information is presented through the interactive Kenya map, county details, historical records and alerts interface.

## Machine Learning Model

The project implements a **Random Forest Classifier** to categorise environmental conditions into three flood risk levels:

- Low Risk
- Medium Risk
- High Risk

The final selected model is **H_S07_T300**, which uses 300 decision trees and seven predictors.

A High-risk probability threshold of 0.44 is applied as part of the classification decision rule.

The model was trained and evaluated using chronological data partitions to maintain the separation between training, validation and testing records.

### Model Evaluation Results

The final model was evaluated on 24,854 reserved real county records from 2024–2025.

| Evaluation Metric | Result |
|---|---:|
| Accuracy | 77.79% |
| Balanced Accuracy | 74.03% |
| Macro F1 Score | 74.50% |
| Weighted F1 Score | 77.29% |
| Macro ROC-AUC | 91.90% |
| Matthews Correlation Coefficient | 0.6422 |

### Classification Performance

| Risk Category | Precision | Recall | F1 Score |
|---|---:|---:|---:|
| Low | 75.35% | 93.42% | 83.42% |
| Medium | 82.64% | 71.00% | 76.38% |
| High | 71.17% | 57.67% | 63.71% |

These results measure agreement with the constructed historical reference labels. They should not be interpreted as independently verified real-world flood forecasting accuracy.

## Technology Stack

The platform was developed using the following technologies:

| Technology | Purpose |
|---|---|
| Python | Main programming language and data processing. |
| Django | Backend web application framework. |
| PostgreSQL | Relational database management. |
| Scikit-learn | Random Forest model development and prediction. |
| Pandas | Data cleaning, transformation and analysis. |
| NumPy | Numerical processing. |
| Joblib | Saving and loading the trained machine learning model. |
| Leaflet.js | Interactive geographical map visualisation. |
| HTML, CSS and JavaScript | Frontend development and user interface. |
| Git and GitHub | Version control and source code management. |
| NASA POWER API | Environmental data acquisition. |
| Open-Meteo API | Current-day weather data acquisition. |

## Geographic Coverage

The historical modelling dataset covers 34 Kenyan counties over the period 2010–2025.

The dataset contains:

- 5,844 calendar days.
- 34 counties with historical environmental predictors.
- 198,696 county-day records.
- 29 historical flood events from EM-DAT.
- 16 retained DAHITI water-level stations.

The dashboard map represents all 47 Kenyan counties. However, historical model predictor coverage is available for 34 counties. The remaining counties are not assigned historical model coverage through synthetic data.

## Project Limitations

The following limitations define the current implementation:

- Historical model predictor coverage is limited to 34 of Kenya's 47 counties.
- Physical IoT sensor hardware was not manufactured or deployed.
- Simulated IoT readings are kept separate from production predictions.
- The application runs locally and depends on the local computer being powered on for scheduled data refreshes.
- Internet connectivity is required for external API acquisition and online map resources.
- External SMS delivery and national emergency broadcasting are not implemented.
- The model is evaluated against constructed historical reference labels, rather than independently verified prospective flood events.
- Real-world warning performance and physical sensor integration have not been established.

## Future Improvements

Potential areas for future development include:

- Integrating physical IoT sensors for actual environmental measurements.
- Expanding historical environmental data coverage to all 47 Kenyan counties.
- Implementing SMS and email alert delivery.
- Deploying the application to a production hosting environment.
- Improving real-time monitoring and automated data acquisition.
- Incorporating additional hydrological and environmental data sources.
- Continuously evaluating and improving model performance as more reliable observations become available.

## Project Repository

**GitHub Repository:** [Kenya Flood Monitoring and Prediction Platform](https://github.com/LauraMaithya/Kenya-flood-risk-platform)


**Project:** An IoT-Based Flood Monitoring Platform Using Random Forest Classification for Real-Time Data Display and Flood Prediction.

**Academic Year:** 2026
