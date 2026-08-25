select * from (
    values
        (1, 'Alice Anders', 'enterprise'),
        (2, 'Bob Baker', 'smb'),
        (3, 'Carol Chen', 'enterprise')
) as t(customer_id, customer_name, customer_segment)
