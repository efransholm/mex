import SwiftUI

struct ContentView: View {
    @State private var count = 0

    var body: some View {
        VStack {
            Image(systemName: "globe")
                .imageScale(.large)
                .foregroundStyle(.tint)

            Text("Hello, world!")
            Text("Count: \(count)")
            Text(count > 5 ? "High" : "Low")
                .foregroundStyle(count > 5 ? .green : .secondary)

            Button("Tap me") {
                count += 1
            }
        }
        .padding()
    }
}

#Preview {
    ContentView()
}
