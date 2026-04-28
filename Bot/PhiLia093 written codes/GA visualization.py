import random
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

TARGET = "HELLO WORLD"
GENE_POOL = "ABCDEFGHIJKLMNOPQRSTUVWXYZ "  # Letters + space
POP_SIZE = 50
MUTATION_RATE = 0.05
GENERATIONS = 1000

def create_individual():
    return ''.join(random.choice(GENE_POOL) for _ in range(len(TARGET)))

def fitness(individual):
    """Count how many characters match the target"""
    return sum(1 for i, t in zip(individual, TARGET) if i == t)

def select_parent(population, fitnesses):
    """Tournament selection"""
    tournament = random.sample(list(zip(population, fitnesses)), 3)
    return max(tournament, key=lambda x: x[1])[0]

def crossover(parent1, parent2):
    """Single point crossover"""
    point = random.randint(1, len(TARGET)-1)
    return parent1[:point] + parent2[point:]

def mutate(individual):
    """Randomly change one character"""
    if random.random() < MUTATION_RATE:
        idx = random.randint(0, len(TARGET)-1)
        individual = list(individual)
        individual[idx] = random.choice(GENE_POOL)
        return ''.join(individual)
    return individual

population = [create_individual() for _ in range(POP_SIZE)]
best_fitness_history = []
avg_fitness_history = []
best_individuals = []

for gen in range(GENERATIONS):
    fitnesses = [fitness(ind) for ind in population]
    best_idx = max(range(POP_SIZE), key=lambda i: fitnesses[i])
    best_individual = population[best_idx]
    best_fitness = fitnesses[best_idx]

    best_fitness_history.append(best_fitness)
    avg_fitness_history.append(sum(fitnesses)/POP_SIZE)
    best_individuals.append(best_individual)

    new_population = []
    for _ in range(POP_SIZE//2):
        parent1 = select_parent(population, fitnesses)
        parent2 = select_parent(population, fitnesses)
        child1 = mutate(crossover(parent1, parent2))
        child2 = mutate(crossover(parent2, parent1))
        new_population.extend([child1, child2])

    population = new_population[:POP_SIZE]

    if gen % 20 == 0 or best_fitness == len(TARGET):
        print(f"Gen {gen:3d}: '{best_individual}' (fitness: {best_fitness}/{len(TARGET)})")

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

ax1.plot(best_fitness_history, 'r-', label='Best Fitness', linewidth=2)
ax1.plot(avg_fitness_history, 'b--', label='Average Fitness', alpha=0.7)
ax1.axhline(y=len(TARGET), color='g', linestyle=':', label='Target')
ax1.set_xlabel('Generation')
ax1.set_ylabel('Fitness')
ax1.set_title('Genetic Algorithm Progress')
ax1.legend()
ax1.grid(True, alpha=0.3)

text_display = ax2.text(0.5, 0.5, '', ha='center', va='center', 
                        fontsize=14, fontfamily='monospace')
ax2.axis('off')
ax2.set_title('Best Individual Evolution')

def animate(frame):
    if frame < len(best_individuals):
        display_text = f"Gen {frame}: '{best_individuals[frame]}'\n"
        display_text += f"Matches: {best_fitness_history[frame]}/{len(TARGET)}"
        text_display.set_text(display_text)

        matches = best_fitness_history[frame]
        color = 'green' if matches == len(TARGET) else 'blue'
        text_display.set_color(color)
    return text_display,

ani = FuncAnimation(fig, animate, frames=range(len(best_individuals)), 
                    interval=50, blit=True, repeat=False)

plt.tight_layout()

print(f"\n🎉 Final Result: '{best_individuals[-1]}'")
print(f"   Fitness: {best_fitness_history[-1]}/{len(TARGET)}")

plt.show()