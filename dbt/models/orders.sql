select * from (
    values
        (101, 1, date '2026-01-05', 250.00),
        (102, 1, date '2026-02-10', 90.50),
        (103, 2, date '2026-02-11', 40.00),
        (104, 3, date '2026-03-01', 610.25)
) as t(order_id, customer_id, order_date, order_amount)
