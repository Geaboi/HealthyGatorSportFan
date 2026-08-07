Labfront acts as a third-party research aggregation wrapper over Garmin's API/SDK platform. While it simplifies project management, its data collection methods introduce notable limitations and points of friction when compared to direct, native Garmin telemetry collection.

### Key Limitations of Labfront

* **Proprietary "Black Box" Algorithms:** Many higher-level metrics provided by Labfront (e.g., Garmin Stress Scores, HRV Values, Sleep Scores) are pre-calculated by black-box algorithms. This introduces methodological uncertainty because the underlying raw math and inputs cannot be audited or modified.


* **No Direct Non-Wear Indicator Field:** Exported datasets lack an explicit binary `is_worn` or wear-status flag. Non-wear must be indirectly inferred using missing timestamps, confidence scores, or synchronization statuses.


* **File Delivery Structure & Storage Friction:** Data is exported in batch `.zip` files containing fragmented, time-bucketed CSVs across separate measurement directories rather than continuous database streaming or unified flat-file updates.


* **Sync Latency & Processing Buffers:** Data synced from the watch takes an additional 2 to 5 minutes (or longer for high-volume raw streams like Beat-to-Beat Intervals) to process and become available in Labfront.



---

### Key Points Where Labfront Conflicts with Native Garmin Data Collection

| Feature / Metric | Native Garmin Telemetry Paradigm | Labfront Processing Paradigm | Functional Friction / Conflict |
| --- | --- | --- | --- |
| **Wear Detection** | Garmin hardware uses optical PPG sensor contact and accelerometer states to flag active wear/non-wear on-device. | Strips direct wear status flags from CSV exports. BBI streams continue recording even when signal confidence drops to `0`.

 | Forces researchers to infer non-wear via proxy metrics (e.g., null values or low confidence flags) rather than explicit status.

 |
| **Data Granularity vs. Aggregation** | Garmin provides raw continuous sensor streams or immediate 1-second/epoch outputs via Health API/Standard SDK. | Aggregates HRV into 5-minute averages (`garmin-connect-hrv-values`) or single nightly summaries.

 | 5-minute averages or nightly summaries are too coarse for instant, real-time intervention triggers.

 |
| **Pipeline Architecture** | Real-time REST API webhooks / direct BLE bluetooth streaming to mobile clients. | Offline batch exports via CSV/ZIP downloads. Adds a 2–5 minute cloud processing delay after syncing.

 | Limits real-time Just-In-Time Adaptive Intervention (JITAI) capabilities that depend on immediate sensor feedback.

 |
| **Dashboard Status Distinctions** | Garmin distinguishes between sensor disconnects, sync failures, and off-body sensor states. | Labfront dashboard groups missing data into broad buckets (*No HR Data*, *Haven't Synced*).

 | Obscures whether data loss stems from participant non-compliance (removing watch) versus hardware/sync errors.

 |