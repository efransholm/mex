// CBO example — Chidamber & Kemerer strict definition
//
// Expected CBO (approximate, depends on bidirectional pass):
//   OrderService        → 3  (OrderRepository, PaymentService, NotificationService)
//   OrderRepository     → 1  (used by OrderService — bidirectional)
//   PaymentService      → 1  (used by OrderService — bidirectional)
//   NotificationService → 1  (used by OrderService — bidirectional)
//   ReportService       → 2  (OrderRepository, NotificationService)
//   Order               → 0  (never referenced via navigation expressions)
//
// What triggers coupling here:
//   - orderRepository.save(order:)     → method call on typed stored property
//   - orderRepository.delete(id:)      → method call on typed stored property
//   - paymentService.charge(...)       → method call on typed stored property
//   - paymentService.refund(orderId:)  → method call on typed stored property
//   - notificationService.notify(...)  → method call on typed stored property

class Order {
    var userId: Int
    var amount: Double
    init(userId: Int, amount: Double) {
        self.userId = userId
        self.amount = amount
    }
}

class OrderRepository {
    func findById(id: Int) -> Order? { return nil }
    func save(order: Order) {}
    func delete(id: Int) {}
}

class PaymentService {
    func charge(amount: Double, userId: Int) -> Bool { return true }
    func refund(orderId: Int) {}
}

class NotificationService {
    func notify(userId: Int, message: String) {}
}

// OrderService is coupled to 3 other classes.
// Stored properties have explicit type annotations so the scope resolver
// can map  orderRepository → OrderRepository, etc.
class OrderService {
    var orderRepository: OrderRepository
    var paymentService: PaymentService
    var notificationService: NotificationService

    init(orderRepository: OrderRepository,
         paymentService: PaymentService,
         notificationService: NotificationService) {
        self.orderRepository = orderRepository
        self.paymentService = paymentService
        self.notificationService = notificationService
    }

    func placeOrder(userId: Int, amount: Double) -> Order? {
        let success = paymentService.charge(amount: amount, userId: userId)
        if success {
            let order = Order(userId: userId, amount: amount)
            orderRepository.save(order: order)
            notificationService.notify(userId: userId, message: "Order placed")
            return order
        }
        return nil
    }

    func cancelOrder(orderId: Int, userId: Int) {
        paymentService.refund(orderId: orderId)
        orderRepository.delete(id: orderId)
        notificationService.notify(userId: userId, message: "Order cancelled")
    }
}

// ReportService is coupled to 2 classes.
class ReportService {
    var orderRepository: OrderRepository
    var notificationService: NotificationService

    init(orderRepository: OrderRepository, notificationService: NotificationService) {
        self.orderRepository = orderRepository
        self.notificationService = notificationService
    }

    func generateSummary(userId: Int) {
        let order = orderRepository.findById(id: userId)
        notificationService.notify(userId: userId, message: "Report ready")
    }
}
