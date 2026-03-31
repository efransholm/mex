// CBO example — Chidamber & Kemerer strict definition
//
// Expected CBO (approximate, depends on bidirectional pass):
//   OrderService        → 3  (OrderRepository, PaymentService, NotificationService)
//   OrderRepository     → 1  (used by OrderService — bidirectional)
//   PaymentService      → 1  (used by OrderService — bidirectional)
//   NotificationService → 1  (used by OrderService — bidirectional)
//   Order               → 0  (never referenced via navigation expressions)
//
// What triggers coupling here:
//   - orderRepository.save(order)     → method call on typed field
//   - orderRepository.delete(id)      → method call on typed field
//   - paymentService.charge(amount)   → method call on typed field
//   - paymentService.refund(orderId)  → method call on typed field
//   - notificationService.notify(...) → method call on typed field

class Order(val userId: Int, val amount: Double)

class OrderRepository {
    fun findById(id: Int): Order? = null
    fun save(order: Order) {}
    fun delete(id: Int) {}
}

class PaymentService {
    fun charge(amount: Double, userId: Int): Boolean = true
    fun refund(orderId: Int) {}
}

class NotificationService {
    fun notify(userId: Int, message: String) {}
}

// OrderService is coupled to 3 other classes.
// The constructor parameters have explicit types so the scope resolver
// can map  orderRepository → OrderRepository, etc.
class OrderService(
    val orderRepository: OrderRepository,
    val paymentService: PaymentService,
    val notificationService: NotificationService
) {
    fun placeOrder(userId: Int, amount: Double): Order? {
        val success = paymentService.charge(amount, userId)
        if (success) {
            val order = Order(userId, amount)
            orderRepository.save(order)
            notificationService.notify(userId, "Order placed")
            return order
        }
        return null
    }

    fun cancelOrder(orderId: Int, userId: Int) {
        paymentService.refund(orderId)
        orderRepository.delete(orderId)
        notificationService.notify(userId, "Order cancelled")
    }
}

// ReportService is coupled to 2 classes.
class ReportService(
    val orderRepository: OrderRepository,
    val notificationService: NotificationService
) {
    fun generateSummary(userId: Int) {
        val order = orderRepository.findById(userId)
        notificationService.notify(userId, "Report ready")
    }
}
