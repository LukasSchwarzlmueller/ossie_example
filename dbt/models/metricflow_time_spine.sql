select cast(range as date) as date_day
from range(date '2020-01-01', date '2030-01-01', interval 1 day)
