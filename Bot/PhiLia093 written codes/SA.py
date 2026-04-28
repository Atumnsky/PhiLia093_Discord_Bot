import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.patches import Circle
import math

def objective_function(x):
    return np.sin(0.5 * x) * np.cos(2 * x) + 0.02 * (x - 2)**2

def simulated_annealing(initial_temp, cooling_rate, iterations):
    # Initial random position
    current_x = np.random.uniform(-10, 10)
    current_energy = objective_function(current_x)

    best_x = current_x
    best_energy = current_energy

    history = [current_x]
    energies = [current_energy]
    temps = [initial_temp]

    for i in range(iterations):
        # Current temperature
        temp = initial_temp * math.exp(-cooling_rate * i)

        neighbor_x = current_x + np.random.normal(0, 2)  # Step size
        neighbor_energy = objective_function(neighbor_x)

        delta_energy = neighbor_energy - current_energy

        if delta_energy < 0:
            # Always accept better solutions
            accept = True
        else:
            # Accept worse solutions with probability exp(-ΔE/T)
            acceptance_prob = math.exp(-delta_energy / temp)
            accept = np.random.random() < acceptance_prob

        if accept:
            current_x = neighbor_x
            current_energy = neighbor_energy

            if current_energy < best_energy:
                best_x = current_x
                best_energy = current_energy

        history.append(current_x)
        energies.append(current_energy)
        temps.append(temp)

    return best_x, best_energy, history, energies, temps

def create_visualization():
    # Parameters
    initial_temp = 100.0
    cooling_rate = 0.05
    iterations = 200

    best_x, best_energy, history, energies, temps = simulated_annealing(
        initial_temp, cooling_rate, iterations
    )

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 12))
    fig.suptitle('Simulated Annealing Visualization', fontsize=16, fontweight='bold')

    x_vals = np.linspace(-10, 10, 1000)
    y_vals = objective_function(x_vals)

    ax1.plot(x_vals, y_vals, 'b-', alpha=0.7, linewidth=2, label='Objective function')
    ax1.set_xlabel('x')
    ax1.set_ylabel('f(x)')
    ax1.set_title('Search Space and Annealing Path')
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim([-10, 10])
    ax1.set_ylim([min(y_vals) - 0.5, max(y_vals) + 0.5])

    current_point, = ax1.plot([], [], 'ro', markersize=10, label='Current position')
    path_line, = ax1.plot([], [], 'r-', alpha=0.5, linewidth=1)
    best_point = Circle((0, 0), 0.3, color='green', alpha=0.7)
    ax1.add_patch(best_point)

    ax1.legend()

    ax2.set_xlabel('Iteration')
    ax2.set_ylabel('Current f(x)')
    ax2.set_title('Energy (Objective Value) Over Time')
    ax2.grid(True, alpha=0.3)
    energy_line, = ax2.plot([], [], 'r-', linewidth=2, label='Current energy')
    best_energy_line, = ax2.plot([], [], 'g--', linewidth=2, label='Best energy found')
    ax2.legend()
    ax2.set_xlim([0, iterations])
    ax2.set_ylim([min(energies) - 0.2, max(energies) + 0.2])

    ax3.set_xlabel('Iteration')
    ax3.set_ylabel('Temperature')
    ax3.set_title('Temperature Schedule (Cooling)')
    ax3.grid(True, alpha=0.3)
    temp_line, = ax3.plot([], [], 'orange', linewidth=2)
    ax3.set_xlim([0, iterations])
    ax3.set_ylim([0, initial_temp * 1.1])

    temp_text = ax1.text(0.02, 0.95, '', transform=ax1.transAxes, 
                        fontsize=10, verticalalignment='top',
                        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    energy_text = ax1.text(0.02, 0.85, '', transform=ax1.transAxes,
                          fontsize=10, verticalalignment='top',
                          bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    def update(frame):
        if frame >= len(history):
            return

        current_x = history[frame]
        current_y = energies[frame]

        current_point.set_data([current_x], [current_y])

        path_line.set_data(history[:frame+1], energies[:frame+1])

        best_idx = np.argmin(energies[:frame+1])
        best_x = history[best_idx]
        best_y = energies[best_idx]
        best_point.center = (best_x, best_y)

        energy_line.set_data(range(frame+1), energies[:frame+1])

        best_energies = [min(energies[:i+1]) for i in range(frame+1)]
        best_energy_line.set_data(range(frame+1), best_energies)

        temp_line.set_data(range(frame+1), temps[:frame+1])

        temp_text.set_text(f'Temp: {temps[frame]:.2f}\nIteration: {frame}')
        energy_text.set_text(f'Current f(x): {current_y:.3f}\nBest f(x): {best_y:.3f}')

        return current_point, path_line, best_point, energy_line, best_energy_line, temp_line, temp_text, energy_text

    anim = animation.FuncAnimation(
        fig, update, frames=min(len(history), iterations),
interval=100, blit=False, repeat=True
    )

    plt.tight_layout()
    plt.show()

    print(f"\n✨ Final Results:")
    print(f"Best x found: {best_x:.4f}")
    print(f"Best f(x) value: {best_energy:.4f}")
    print(f"Total iterations: {iterations}")
    print(f"Initial temperature: {initial_temp}")
    print(f"Cooling rate: {cooling_rate}")

if __name__ == "__main__": 
    create_visualization()