import SwiftUI

struct CounterView: View {
    // Observable state variables
    @State private var count: Int = 0
    @State private var isEnabled: Bool = true
    @Binding var sharedValue: String
    
    let title = "Counter App"  // Immutable
    
    var body: some View {
        VStack {
            Text(title)
            Text("Count: \(count)")
            
            Button("Increment") {
                count += 1  // State update
                count = count + 1  // Another state update
            }
            .disabled(!isEnabled)
            
            Button("Toggle") {
                isEnabled.toggle()  // State update
            }
            
            TextField("Value", text: $sharedValue)
        }
    }
}

class ViewModel: ObservableObject {
    @Published var errorMessage: String? = nil  // Observable
    @Published var items: [String] = []  // Observable
    
    let appName = "MyApp"  // Immutable
    var isLoading: Bool = false  // Mutable
    
    func updateItems(_ newItems: [String]) {
        items = newItems  // State update
    }
    
    func addItem(_ item: String) {
        items.append(item)  // State update
    }
    
    func clearItems() {
        items.removeAll()  // State update
    }
}