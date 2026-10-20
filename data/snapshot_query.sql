WITH 
lines AS (
 SELECT StoreJobLine_ID, StoreJob_ID, Store_ID, Created
 FROM `p-plat-datadf-l1st.L1_LogisticsViews.v_StoreJobLines`
 QUALIFY ROW_NUMBER() OVER(PARTITION BY StoreJobLine_ID ORDER BY load_timestamp DESC)=1
), jobs AS (
 SELECT StoreJob_ID, Branch_ID, DepartureLimitTime
 FROM `p-plat-datadf-l1st.L1_LogisticsViews.v_StoreJobs`
 QUALIFY ROW_NUMBER() OVER(PARTITION BY StoreJob_ID ORDER BY load_timestamp DESC)=1
), states AS (
 SELECT StoreJobLine_ID, PickedDate, StornoDate
 FROM `p-plat-datadf-l1st.L1_LogisticsViews.v_StoreJobLineStates`
 QUALIFY ROW_NUMBER() OVER(PARTITION BY StoreJobLine_ID ORDER BY load_timestamp DESC)=1
), stores AS (
 SELECT Store_ID, Store
 FROM `p-plat-datadf-l1st.L1_LogisticsViews.v_Stores`
 QUALIFY ROW_NUMBER() OVER(PARTITION BY Store_ID ORDER BY load_timestamp DESC)=1
), canonical AS (
 SELECT l.StoreJobLine_ID AS jobline_id, l.Created AS created_at,
 s.PickedDate AS picked_at, j.DepartureLimitTime AS cutoff_at,
 CAST(j.Branch_ID AS STRING) AS branch_id, CAST(l.Store_ID AS STRING) AS store_id,
 st.Store AS store_name, s.StornoDate IS NOT NULL AS is_cancelled
 FROM lines l LEFT JOIN jobs j USING(StoreJob_ID)
 LEFT JOIN states s USING(StoreJobLine_ID) LEFT JOIN stores st USING(Store_ID)
),
cohort AS (
 SELECT * FROM canonical
 WHERE created_at >= @start AND created_at < @end
 AND (branch_id = @branch_id OR STRPOS(UPPER(COALESCE(store_name, '')), @store_pattern) > 0
      OR STRPOS(UPPER(COALESCE(store_id, '')), @store_pattern) > 0)
), validated AS (
 SELECT *, COUNT(*) OVER(PARTITION BY jobline_id) AS id_occurrences FROM cohort
), buckets AS (
 SELECT store_id, TIMESTAMP_TRUNC(created_at,HOUR,@timezone) AS created_at,
 IF(created_at=TIMESTAMP_TRUNC(created_at,HOUR,@timezone),created_at,
    TIMESTAMP_ADD(TIMESTAMP_TRUNC(created_at,HOUR,@timezone),INTERVAL 1 HOUR)) AS ready_at,
 TIMESTAMP_TRUNC(picked_at,HOUR,@timezone) AS picked_at,
 cutoff_at, is_cancelled,
 jobline_id IS NULL OR id_occurrences > 1 AS invalid_id,
 picked_at < created_at AS invalid_order
 FROM validated
)
SELECT store_id, created_at, ready_at, picked_at, cutoff_at, is_cancelled,
 invalid_id, invalid_order, COUNT(*) AS jobline_count
FROM buckets GROUP BY 1,2,3,4,5,6,7,8
ORDER BY created_at, store_id
