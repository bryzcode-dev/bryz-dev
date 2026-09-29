connection: "warehouse"
include: "/views/*.view.lkml"
explore: orders {
  from: orders
  join: customers { sql_on: ${orders.customer_id} = ${customers.id} ;; }
}
