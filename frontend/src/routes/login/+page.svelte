<script lang="ts">
  let username = "";
  let password = "";
  let loading = false;
  let errorMessage = "";

  async function handleLogin(event: Event) {
    event.preventDefault();
    loading = true;
    errorMessage = "";

    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!response.ok) {
        const data = await response.json();
        errorMessage = data.detail ?? "Invalid username or password.";
        return;
      }

      window.location.href = "/dashboard/predictions";
    } catch (err) {
      errorMessage = "Network error. Is the backend running?";
    } finally {
      loading = false;
    }
  }
</script>

<section class="login-page">
  <div class="login-card">
    <h1>GCC Dashboard</h1>
    <p>Please sign in to continue.</p>

    <form on:submit={handleLogin}>
      <label>
        Username
        <input
          type="text"
          bind:value={username}
          placeholder="Username"
          required
          disabled={loading}
        />
      </label>

      <label>
        Password
        <input
          type="password"
          bind:value={password}
          placeholder="Password"
          required
          disabled={loading}
        />
      </label>

      {#if errorMessage}
        <div class="error">{errorMessage}</div>
      {/if}

      <button type="submit" disabled={loading}>
        {loading ? "Signing in..." : "Sign in"}
      </button>
    </form>
  </div>
</section>

<style>
  .login-page {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    background: #f3f4f6;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      Oxygen, Ubuntu, Cantarell, "Open Sans", "Helvetica Neue", sans-serif;
  }

  .login-card {
    background: white;
    border: 1px solid #ddd;
    border-radius: 16px;
    padding: 2.5rem;
    width: 100%;
    max-width: 400px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
  }

  h1 {
    font-size: 1.75rem;
    font-weight: 700;
    margin: 0 0 0.5rem 0;
  }

  p {
    color: #6b7280;
    margin: 0 0 1.5rem 0;
  }

  form {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    font-weight: 600;
  }

  input {
    padding: 0.7rem;
    border: 1px solid #ccc;
    border-radius: 8px;
    font-size: 1rem;
  }

  button {
    padding: 0.8rem;
    border: none;
    border-radius: 8px;
    background: #111827;
    color: white;
    font-weight: 600;
    font-size: 1rem;
    cursor: pointer;
  }

  button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .error {
    color: #b91c1c;
    background: #fef2f2;
    border: 1px solid #ef4444;
    border-radius: 8px;
    padding: 0.8rem;
    font-size: 0.95rem;
  }
</style>
