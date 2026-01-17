Feature: User Login Authentication

  As a registered user
  I want to log in with my credentials
  So that I can access my private account areas

  # --- Positive Cases (Happy Path) ---

  Scenario: Successful login with valid standard credentials
    Given the user is on the login page
    When the user enters a valid username "standard_user" and a valid password "secret_sauce"
    And clicks the "Login" button
    Then the user should be redirected to the "Dashboard" page
    And a confirmation message "Welcome back!" should be displayed

  Scenario Outline: Successful login with different valid credentials
    Given the user is on the login page
    When the user enters a valid username "<username>" and a valid password "<password>"
    And clicks the "Login" button
    Then the user should be redirected to the "Dashboard" page

    Examples:
      | username         | password     |
      | testuser_01      | pass123      |
      | system_admin     | Admin_P@ss   |

  # --- Negative Cases (Failure Paths) ---

  Scenario: Login failure due to invalid password
    Given the user is on the login page
    When the user enters a valid username "standard_user" and an invalid password "incorrect_password"
    And clicks the "Login" button
    Then the user should remain on the login page
    And an error message "Invalid credentials provided." should be displayed
    And the password field should be cleared

  Scenario: Login failure due to unregistered username
    Given the user is on the login page
    When the user enters an unregistered username "unknown_user_404" and a password "any_password"
    And clicks the "Login" button
    Then an error message "Username not found or password incorrect." should be displayed

  Scenario: Login failure with both fields empty
    Given the user is on the login page
    When the user enters an empty username "" and an empty password ""
    And clicks the "Login" button
    Then an error message "Username is required." should be displayed

  Scenario: Login failure with username containing SQL injection attempt
    Given the user is on the login page
    When the user enters a username "' OR '1'='1" and a password "secret_sauce"
    And clicks the "Login" button
    Then an error message "Invalid credentials provided." should be displayed
    And a log entry for a security warning should be generated

  # --- Boundary Cases ---

  Scenario: Login failure due to case mismatch in username (Case Sensitivity Test)
    Given the user is on the login page
    When the user enters a username "Standard_user" (incorrect capitalization) and a valid password "secret_sauce"
    And clicks the "Login" button
    Then an error message "Invalid credentials provided." should be displayed

  Scenario: Login failure due to leading space in username (Input trimming test)
    Given the user is on the login page
    When the user enters a username with a leading space " standard_user" and a valid password "secret_sauce"
    And clicks the "Login" button
    Then the user should remain on the login page
    And an error message "Invalid credentials provided." should be displayed
    # If the system automatically trims input, this should be a positive test instead. Assuming failure for robustness.

  Scenario: Successful login using minimum character length inputs
    Given the system accepts a minimum username length of 3 and minimum password length of 6
    When the user enters the minimum length valid username "bob" and minimum length valid password "p@ssw0rd"
    And clicks the "Login" button
    Then the user should be redirected to the "Dashboard" page

  Scenario: Login failure when exceeding maximum allowed password length
    Given the system has a maximum password length limit of 50 characters
    When the user enters a valid username "standard_user" and a password exceeding 50 characters
    And clicks the "Login" button
    Then the user should remain on the login page
    And an error message "Password is too long." should be displayed
    And the password field should reject input beyond 50 characters
```